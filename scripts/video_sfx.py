#!/usr/bin/env python3
"""Inspect media, render cue plans and validate isolated local Foley deliveries."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urldefrag
import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import zipfile
import numpy as np
import requests
import soundfile as sf
from PIL import Image, ImageDraw
from scipy.signal import resample_poly
from sfx_engine import RATE, TYPES, mix_events

for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')

def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def execute(command):
    result=subprocess.run(command,capture_output=True)
    if result.returncode:
        raise ValueError(result.stderr.decode('utf-8',errors='replace').strip() or 'Media command failed')
    return result.stdout

def probe(path,ffprobe):
    return json.loads(execute([ffprobe,'-v','error','-show_streams','-show_format','-of','json',str(path)]))

def media_info(path,ffprobe):
    path=Path(path).resolve()
    if not path.is_file():raise ValueError('Media file does not exist: '+str(path))
    if path.suffix.lower()=='.gif':
        with Image.open(path) as im:
            durations=[]
            for index in range(im.n_frames):
                im.seek(index);delay=im.info.get('duration')
                if delay is None or delay<=0:raise ValueError('GIF contains missing or zero frame delays; inspect its playback timing first')
                durations.append(delay/1000)
            return {'source':path.name,'kind':'gif','width':im.width,'height':im.height,
                    'frames':im.n_frames,'duration_seconds':round(sum(durations),6),
                    'frame_starts_seconds':np.cumsum([0]+durations[:-1]).round(6).tolist(),
                    'frame_durations_seconds':durations}
    data=probe(path,ffprobe)
    video=next((s for s in data['streams'] if s['codec_type']=='video'),None)
    if video is None:raise ValueError('The source has no video stream')
    duration=float(video.get('duration',data['format'].get('duration',0)))
    if not math.isfinite(duration) or duration<=0:raise ValueError('Cannot determine a positive video duration')
    return {'source':path.name,'kind':'video','width':video['width'],'height':video['height'],
            'frames':int(video['nb_frames']) if video.get('nb_frames','').isdigit() else None,
            'duration_seconds':duration,'frame_rate':video.get('avg_frame_rate')}

def inspect_media(path,out,ffmpeg,ffprobe):
    path=Path(path).resolve();out=Path(out);meta=media_info(path,ffprobe);out.mkdir(parents=True,exist_ok=True)
    dump(out/'media.json',meta)
    if meta['kind']=='gif':
        with Image.open(path) as im:
            board=Image.new('RGB',(960,3*202),'#11171c');draw=ImageDraw.Draw(board)
            for index in range(12):
                frame=round(index*(im.n_frames-1)/11);im.seek(frame)
                thumb=im.convert('RGB');thumb.thumbnail((240,180))
                x,y=index%4*240,index//4*202;board.paste(thumb,(x,y))
                draw.text((x+4,y+183),f"{meta['frame_starts_seconds'][frame]:.3f}s | frame {frame}",fill='white')
            board.save(out/'contact.jpg',quality=90)
    else:
        data=execute([ffmpeg,'-hide_banner','-loglevel','error','-i',str(path),'-an',
                      '-vf',f"fps={12/meta['duration_seconds']:.9f},scale=240:-1,tile=4x3",'-frames:v','1',
                      '-f','image2pipe','-vcodec','mjpeg','-'])
        (out/'contact.jpg').write_bytes(data)
    return meta

def number(value,name,minimum=None,maximum=None):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError(name+' must be a finite number')
    if minimum is not None and value<minimum:raise ValueError(name+' is below its minimum')
    if maximum is not None and value>maximum:raise ValueError(name+' is above its maximum')
    return value

def load_plan(file,ffprobe):
    file=Path(file).resolve();plan=json.loads(file.read_text(encoding='utf-8'))
    if plan.get('version')!=1:raise ValueError('The cue plan requires version 1')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',plan.get('id','')):raise ValueError('id must be a simple file-safe identifier')
    source=plan.get('source')
    if not isinstance(source,str) or not source:raise ValueError('source must be a local media path')
    if urlparse(source).scheme in ('http','https'):raise ValueError('Download the source to a local file before rendering')
    source=(file.parent/source).resolve();media=media_info(source,ffprobe);duration=media['duration_seconds']
    seed=plan.get('seed',20261019)
    if isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<2**64:raise ValueError('seed must be a nonnegative 64-bit integer')
    events=plan.get('events')
    if not isinstance(events,list):raise ValueError('events must be a list')
    seen=set()
    param_keys={'whoosh':{'low_hz','high_hz','power'},'impact':{'material'},'mud':set(),
                'scatter':{'count','material'},'rotor':set(),'suction':set(),'bubble':set(),'sample':{'file','offset'}}
    for event in events:
        if not isinstance(event,dict):raise ValueError('Each event must be an object')
        identifier=event.get('id','')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',identifier) or identifier in seen:raise ValueError('Every event needs a unique file-safe id')
        seen.add(identifier)
        kind=event.get('type')
        if kind not in TYPES:raise ValueError('Unsupported event type: '+str(kind))
        number(event.get('at'),'event.at',0)
        number(event.get('duration'),'event.duration',1/RATE)
        number(event.get('gain',1),'event.gain',0,4)
        number(event.get('pan',0),'event.pan',-1,1)
        if event['at']+event['duration']>duration+1/RATE:raise ValueError('An event extends beyond the source duration')
        params=event.get('params',{})
        if not isinstance(params,dict) or set(params)-param_keys[kind]:raise ValueError('Invalid params for event '+identifier)
    return plan,source,media,file.parent

def verify(manifest,ffmpeg,ffprobe):
    manifest=Path(manifest);data=json.loads(manifest.read_text(encoding='utf-8'));folder=manifest.parent
    wav=folder/data['wav'];audio,rate=sf.read(wav,always_2d=True);info=sf.info(wav)
    if rate!=RATE or info.channels!=2 or info.subtype!='PCM_24':raise ValueError('WAV is not 48 kHz / PCM 24-bit / stereo')
    if len(audio)!=round(data['duration_seconds']*RATE):raise ValueError('WAV duration differs from the source')
    if not np.isfinite(audio).all() or np.max(np.abs(audio),initial=0)>=1:raise ValueError('WAV contains clipping or non-finite samples')
    allowed=np.zeros(len(audio),bool)
    for event in data['events']:
        start=round(event['at']*RATE);end=min(len(audio),start+round(event['duration']*RATE));allowed[start:end]=True
    if np.max(np.abs(audio[~allowed]),initial=0)!=0:raise ValueError('Audio exists outside declared action windows')
    preview=folder/data['preview'];p=probe(preview,ffprobe)
    video=next(s for s in p['streams'] if s['codec_type']=='video');sound=next(s for s in p['streams'] if s['codec_type']=='audio')
    if video['codec_name']!='h264' or sound['codec_name']!='aac' or sound['sample_rate']!='48000' or sound['channels']!=2:raise ValueError('Unexpected preview media format')
    vd=float(video['duration']);ad=float(sound['duration'])
    if abs(vd-data['duration_seconds'])>1/30+.001 or abs(vd-ad)>.035:raise ValueError('Preview duration or audio synchronization differs from the source')
    execute([ffmpeg,'-hide_banner','-loglevel','error','-i',str(preview),'-f','null','-'])
    decoded=np.frombuffer(execute([ffmpeg,'-hide_banner','-loglevel','error','-i',str(preview),'-map','0:a:0','-f','f32le','-']),dtype='<f4')
    if not np.isfinite(decoded).all() or np.max(np.abs(decoded),initial=0)>=1:raise ValueError('Decoded AAC audio clips')
    peak=np.max(np.abs(audio),initial=0);tp=np.max(np.abs(resample_poly(audio,4,1,axis=0)),initial=0)
    return {'passed':True,'duration_seconds':len(audio)/RATE,'sample_rate':rate,'channels':info.channels,
            'subtype':info.subtype,'peak_dbfs':20*math.log10(peak) if peak else -120,
            'true_peak_dbfs':20*math.log10(tp) if tp else -120,'silent_outside_events':True,
            'video_codec':video['codec_name'],'audio_codec':sound['codec_name'],'preview_duration_seconds':vd,
            'wav_sha256':hashlib.sha256(wav.read_bytes()).hexdigest()}

def render_targets(out,plan,stems=False):
    out=Path(out);identifier=plan['id']
    files=[out/(identifier+'.wav'),out/(identifier+'.mp4'),out/'manifest.json',out/'verification.json',out/'cue_sheet.csv']
    if stems:files.extend(out/'stems'/(event['id']+'.wav') for event in plan['events'])
    return files

def protect_outputs(destinations,overwrite):
    if not overwrite and any(p.exists() for p in destinations):raise ValueError('Output already exists; choose a new directory or pass --overwrite')

def render(file,out,ffmpeg,ffprobe,stems=False,overwrite=False):
    plan,source,media,base=load_plan(file,ffprobe);out=Path(out);identifier=plan['id']
    destinations=render_targets(out,plan,stems);protect_outputs(destinations,overwrite)
    wav,preview,manifest=destinations[:3];previous_stems=[]
    if overwrite and manifest.is_file():
        try:previous_stems=json.loads(manifest.read_text(encoding='utf-8')).get('stems',[])
        except (ValueError,AttributeError):pass
        if not isinstance(previous_stems,list):previous_stems=[]
    audio,layers,allowed=mix_events(plan['events'],media['duration_seconds'],plan.get('seed',20261019),base,plan.get('peak_dbfs',-2))
    out.mkdir(parents=True,exist_ok=True)
    sf.write(wav,audio,RATE,subtype='PCM_24')
    if stems:
        (out/'stems').mkdir(exist_ok=True)
        for name,layer in layers.items():sf.write(out/'stems'/(name+'.wav'),layer,RATE,subtype='PCM_24')
    source_options=['-ignore_loop','1','-min_delay','0'] if media['kind']=='gif' else []
    duration=math.ceil(media['duration_seconds']*30-1e-6)/30
    execute([ffmpeg,'-hide_banner','-loglevel','error','-y',*source_options,'-i',str(source),'-i',str(wav),
             '-filter_complex','[0:v:0]pad=ceil(iw/2)*2:ceil(ih/2)*2,fps=30,tpad=stop_mode=clone:stop_duration=0.1[v]',
             '-map','[v]','-map','1:a:0','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p',
             '-c:a','aac','-b:a','192k','-ar','48000','-af','apad','-t',f'{duration:.6f}','-movflags','+faststart',str(preview)])
    methods=sorted({'local_audio_sample' if e['type']=='sample' else 'procedural' for e in plan['events']})
    data={'version':1,'id':identifier,'source':source.name,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'duration_seconds':media['duration_seconds'],'method':methods or ['silence'],'processing':'local',
          'wav':wav.name,'preview':preview.name,'events':plan['events'],'seed':plan.get('seed',20261019),
          'stems':['stems/'+name+'.wav' for name in layers] if stems else [],
          'prompt_notes':plan.get('prompt_notes',{})}
    dump(manifest,data);dump(out/'verification.json',verify(manifest,ffmpeg,ffprobe))
    with (out/'cue_sheet.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=['id','type','at','duration','gain','pan','label']);writer.writeheader()
        for e in plan['events']:writer.writerow({key:e.get(key,'') for key in writer.fieldnames})
    # Remove only explicitly recorded generated stems, after a successful replacement.
    for name in previous_stems:
        if isinstance(name,str) and re.fullmatch(r'stems/[A-Za-z0-9][A-Za-z0-9_-]{0,79}\.wav',name) and name not in data['stems']:
            old=(out/name).resolve()
            if old.is_relative_to(out.resolve()) and old.is_file():old.unlink()
    return {'id':identifier,'manifest':str(manifest),'duration_seconds':media['duration_seconds']}

class MediaLinks(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        for key in ('src','href'):
            if tag in ('img','video','source','a') and values.get(key):self.links.append(values[key])

def collect(url,out):
    if urlparse(url).scheme not in ('http','https'):raise ValueError('collect needs an HTTP(S) page URL')
    page=requests.get(url,timeout=(15,40));page.raise_for_status();parser=MediaLinks();parser.feed(page.text)
    out=Path(out);out.mkdir(parents=True,exist_ok=True);media=[];seen=set();names=set()
    for link in parser.links:
        address=urldefrag(urljoin(page.url,link))[0];parsed=urlparse(address);suffix=Path(parsed.path).suffix.lower()
        if parsed.scheme not in ('http','https') or suffix not in ('.gif','.mp4','.webm','.mov') or address in seen:continue
        seen.add(address);name=re.sub(r'[^A-Za-z0-9_.-]','_',Path(parsed.path).name)
        if name in names:name=Path(name).stem+'-'+hashlib.sha256(address.encode()).hexdigest()[:8]+suffix
        names.add(name);destination=out/name
        if destination.exists():raise ValueError('Reference output already exists: '+name)
        with requests.get(address,stream=True,timeout=(15,40)) as response:
            response.raise_for_status()
            with destination.open('wb') as f:
                for chunk in response.iter_content(1024*1024):f.write(chunk)
        media.append({'url':address,'file':name,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()})
    if not media:raise ValueError('The page contains no directly linked GIF/video files; inspect its browser view or provided download package')
    result={'page':page.url,'media':media};dump(out/'sources.json',result);return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg',default=shutil.which('ffmpeg') or 'ffmpeg')
    parser.add_argument('--ffprobe',default=shutil.which('ffprobe') or 'ffprobe')
    subs=parser.add_subparsers(dest='command',required=True)
    p=subs.add_parser('inspect');p.add_argument('source');p.add_argument('--out',required=True)
    p=subs.add_parser('collect');p.add_argument('url');p.add_argument('--out',required=True)
    for command in ('render','batch'):
        p=subs.add_parser(command);p.add_argument('plan');p.add_argument('--out',required=True)
        p.add_argument('--stems',action='store_true');p.add_argument('--overwrite',action='store_true')
    p=subs.add_parser('verify');p.add_argument('manifest')
    args=parser.parse_args()
    try:
        if args.command=='inspect':result=inspect_media(args.source,args.out,args.ffmpeg,args.ffprobe)
        elif args.command=='collect':result=collect(args.url,args.out)
        elif args.command=='render':result=render(args.plan,args.out,args.ffmpeg,args.ffprobe,args.stems,args.overwrite)
        elif args.command=='verify':result=verify(args.manifest,args.ffmpeg,args.ffprobe)
        else:
            plans=sorted(Path(args.plan).glob('*.json'))
            if not plans:raise ValueError('No JSON cue plans found in the batch directory')
            # Validate every plan before starting a partially successful batch.
            loaded=[(p,load_plan(p,args.ffprobe)[0]) for p in plans]
            if len({plan['id'] for _,plan in loaded})!=len(loaded):raise ValueError('Batch clip ids must be unique')
            out=Path(args.out)
            targets=[out/'index.json',out/'delivery.zip']
            for _,plan in loaded:targets.extend(render_targets(out/plan['id'],plan,args.stems))
            protect_outputs(targets,args.overwrite)
            results=[render(p,out/plan['id'],args.ffmpeg,args.ffprobe,args.stems,args.overwrite) for p,plan in loaded]
            out=Path(args.out);result={'clips':[{'id':r['id'],'manifest':r['id']+'/manifest.json','duration_seconds':r['duration_seconds']} for r in results]}
            dump(out/'index.json',result)
            archive=out/'delivery.zip'
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
                for _,plan in loaded:
                    for file in render_targets(out/plan['id'],plan,args.stems):
                        z.write(file,file.relative_to(out).as_posix())
                z.write(out/'index.json','index.json')
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,KeyError,TypeError,requests.RequestException) as exc:
        print('Error: '+str(exc),file=sys.stderr);return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
