"""Integration contracts: these tests invoke the real CLI and real FFmpeg."""
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
import numpy as np
import soundfile as sf
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/video_sfx.py'
INPUT = ROOT / 'examples/01-projectile-throw/input.mp4'
WORK = ROOT / 'working/tests'
WORK.mkdir(parents=True, exist_ok=True)

def run_cli(*args):
    return subprocess.run([sys.executable,str(CLI),*map(str,args)],capture_output=True,text=True,encoding='utf-8')

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args): pass

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='case-',dir=WORK)
        self.folder=Path(self.temp.name).resolve()
        assert self.folder.is_relative_to(WORK.resolve())
        self.addCleanup(self.temp.cleanup)
    def plan(self,identifier='projectile'):
        return {'version':1,'id':identifier,'source':os.path.relpath(INPUT,self.folder),'seed':20261019,
                'events':[{'id':'throw','type':'whoosh','at':.345,'duration':.36,'gain':.14,'pan':-.08},
                          {'id':'impact','type':'mud','at':1.3666666667,'duration':.27,'gain':.67,'pan':.42},
                          {'id':'scatter','type':'scatter','at':1.39,'duration':.48,'gain':.08,'pan':.42}]}
    def save_plan(self,plan,name='plan.json'):
        p=self.folder/name;p.write_text(json.dumps(plan),encoding='utf-8');return p
    def render(self,plan=None,output='output',stems=False):
        p=self.save_plan(plan or self.plan(),output+'.json');out=self.folder/output
        result=run_cli('render',p,'--out',out,*(['--stems'] if stems else []))
        self.assertEqual(result.returncode,0,result.stderr or result.stdout)
        return out
    def test_inspect_reads_video_duration_and_contact_sheet(self):
        out=self.folder/'inspect';r=run_cli('inspect',INPUT,'--out',out)
        self.assertEqual(r.returncode,0,r.stderr)
        metadata=json.loads((out/'media.json').read_text(encoding='utf-8'))
        self.assertAlmostEqual(metadata['duration_seconds'],2.3,places=4)
        self.assertEqual((metadata['width'],metadata['height']),(960,720))
        with Image.open(out/'contact.jpg') as im:self.assertGreater(im.width,100)
    def test_first_case_wav_contract_and_silent_gaps(self):
        out=self.render();data,rate=sf.read(out/'projectile.wav',always_2d=True)
        self.assertEqual(rate,48000);self.assertEqual(data.shape,(110400,2))
        self.assertEqual(sf.info(out/'projectile.wav').subtype,'PCM_24')
        self.assertLess(np.max(np.abs(data)),.90)
        self.assertGreater(np.max(np.abs(data[66000:73000])),.1)
        self.assertEqual(np.max(np.abs(data[:16000])),0)
        self.assertEqual(np.max(np.abs(data[38400:62400])),0)
        self.assertEqual(np.max(np.abs(data[96000:])),0)
        self.assertGreater(np.sum(data[66000:76000,1]**2),np.sum(data[66000:76000,0]**2))
    def test_repeated_render_is_deterministic(self):
        a=self.render(output='a');b=self.render(output='b')
        self.assertEqual(hashlib.sha256((a/'projectile.wav').read_bytes()).digest(),hashlib.sha256((b/'projectile.wav').read_bytes()).digest())
    def test_custom_high_frequency_whoosh_accepts_a_valid_band(self):
        plan=self.plan();plan['events'][0]['params']={'low_hz':3000,'high_hz':7000}
        out=self.render(plan)
        audio,_=sf.read(out/'projectile.wav',always_2d=True)
        self.assertGreater(np.sqrt(np.mean(audio[17000:33000]**2)),.001)
    def test_stems_sum_to_mix_with_only_pcm_rounding_error(self):
        out=self.render(stems=True);mix,_=sf.read(out/'projectile.wav',always_2d=True)
        stems=[sf.read(p,always_2d=True)[0] for p in (out/'stems').glob('*.wav')]
        self.assertEqual(len(stems),3)
        self.assertLess(np.max(np.abs(sum(stems)-mix)),5/2**23)
    def test_preview_is_h264_aac_and_keeps_duration(self):
        out=self.render();r=run_cli('verify',out/'manifest.json')
        self.assertEqual(r.returncode,0,r.stderr)
        report=json.loads(r.stdout)
        self.assertEqual(report['video_codec'],'h264');self.assertEqual(report['audio_codec'],'aac')
        self.assertLessEqual(abs(report['preview_duration_seconds']-2.3),.034)
    def test_final_ogg_is_vorbis_96kbps_with_the_source_duration(self):
        out=self.render();ogg=out/'projectile.ogg'
        self.assertTrue(ogg.is_file(),'The final OGG delivery was not generated')
        result=subprocess.run([shutil.which('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',str(ogg)],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        media=json.loads(result.stdout);stream=media['streams'][0]
        self.assertEqual(media['format']['format_name'],'ogg')
        self.assertEqual(stream['codec_name'],'vorbis');self.assertEqual(int(stream['bit_rate']),96000)
        decoded,rate=sf.read(ogg,always_2d=True)
        self.assertEqual(rate,48000);self.assertEqual(decoded.shape,(110400,2))
        self.assertTrue(np.isfinite(decoded).all());self.assertLess(np.max(np.abs(decoded)),1)
        report=json.loads(run_cli('verify',out/'manifest.json').stdout)
        self.assertEqual(report['final_audio_codec'],'vorbis')
        self.assertEqual(report['final_audio_bitrate_kbps'],96)
    def test_verify_rejects_a_damaged_final_ogg(self):
        out=self.render();ogg=out/'projectile.ogg'
        self.assertTrue(ogg.is_file())
        ogg.write_bytes(b'not an OGG file')
        result=run_cli('verify',out/'manifest.json')
        self.assertNotEqual(result.returncode,0)
    def make_gif(self,size=(48,32)):
        frames=[Image.new('RGB',size,(i*6,80,170)) for i in range(39)]
        path=self.folder/'held.gif'
        frames[0].save(path,save_all=True,append_images=frames[1:],duration=[40]*38+[450],loop=0,optimize=False)
        return path
    def test_gif_final_hold_is_included_in_wav_and_preview(self):
        gif=self.make_gif();out=self.folder/'gif-inspect';r=run_cli('inspect',gif,'--out',out)
        self.assertEqual(r.returncode,0,r.stderr)
        meta=json.loads((out/'media.json').read_text(encoding='utf-8'))
        self.assertAlmostEqual(meta['duration_seconds'],1.97,places=5)
        self.assertAlmostEqual(meta['frame_starts_seconds'][-1],1.52,places=5)
        p=self.plan('gif');p['source']='held.gif'
        rendered=self.render(p,output='held-render')
        self.assertEqual(sf.info(rendered/'gif.wav').frames,94560)
        report=json.loads(run_cli('verify',rendered/'manifest.json').stdout)
        self.assertAlmostEqual(report['preview_duration_seconds'],2.0,places=3)
    def test_short_gif_delays_reach_the_actual_final_frame(self):
        frames=[Image.new('RGB',(48,32),(i*10,70,120)) for i in range(21)]
        gif=self.folder/'fast.gif'
        frames[0].save(gif,save_all=True,append_images=frames[1:],duration=[10]*20+[300],loop=0,optimize=False)
        plan=self.plan('fast');plan['source']='fast.gif';plan['events']=[]
        out=self.render(plan,output='fast-output')
        self.assertEqual(sf.info(out/'fast.wav').frames,24000)
        result=subprocess.run([shutil.which('ffmpeg'),'-v','error','-i',str(out/'fast.mp4'),
                               '-ss','0.45','-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        rgb=np.frombuffer(result.stdout,dtype=np.uint8).reshape(32,48,3)
        self.assertGreater(np.median(rgb[:,:,0]),180,'The 10 ms GIF frames were slowed down during conversion')
    def test_odd_gif_dimensions_are_padded_for_h264(self):
        self.make_gif(size=(49,33));plan=self.plan('odd');plan['source']='held.gif'
        out=self.render(plan,output='odd-output')
        result=subprocess.run([shutil.which('ffprobe'),'-v','error','-show_streams','-of','json',str(out/'odd.mp4')],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        video=next(s for s in json.loads(result.stdout)['streams'] if s['codec_type']=='video')
        self.assertEqual((video['width'],video['height']),(50,34))
    def test_invalid_events_fail_without_creating_audio(self):
        self.assertEqual(run_cli('--help').returncode,0)
        for field,value in [('at',-.1),('duration',0),('pan',2),('type','environment-bed')]:
            with self.subTest(field=field):
                p=self.plan();p['events'][0][field]=value
                dest=self.folder/('invalid-'+field);r=run_cli('render',self.save_plan(p),'--out',dest)
                self.assertNotEqual(r.returncode,0)
                self.assertEqual(list(dest.glob('*.wav')),[])
    def test_overwrite_requires_explicit_flag(self):
        out=self.render();before=(out/'projectile.wav').read_bytes()
        r=run_cli('render',self.folder/'output.json','--out',out)
        self.assertNotEqual(r.returncode,0)
        self.assertEqual((out/'projectile.wav').read_bytes(),before)
    def test_overwrite_protects_reports_and_requested_stems(self):
        plan=self.save_plan(self.plan())
        for name in ['cue_sheet.csv','verification.json','stems/throw.wav','projectile.ogg']:
            with self.subTest(name=name):
                out=self.folder/('collision-'+name.replace('/','-'));target=out/name
                target.parent.mkdir(parents=True);target.write_bytes(b'keep this file')
                r=run_cli('render',plan,'--out',out,'--stems')
                self.assertNotEqual(r.returncode,0)
                self.assertEqual(target.read_bytes(),b'keep this file')
                self.assertFalse((out/'projectile.wav').exists())
    def test_overwrite_removes_only_obsolete_generated_stems(self):
        out=self.render(stems=True);(out/'stems/keep.wav').write_bytes(b'user file')
        plan=self.plan();plan['events'][0]['id']='release';path=self.save_plan(plan,'changed.json')
        r=run_cli('render',path,'--out',out,'--stems','--overwrite')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse((out/'stems/throw.wav').exists())
        self.assertTrue((out/'stems/release.wav').is_file())
        self.assertEqual((out/'stems/keep.wav').read_bytes(),b'user file')
    def test_batch_preflights_summary_files_before_rendering(self):
        plans=self.folder/'plans';plans.mkdir();p=self.plan('one');p['source']=os.path.relpath(INPUT,plans)
        (plans/'one.json').write_text(json.dumps(p),encoding='utf-8')
        for name in ['index.json','delivery.zip','one/cue_sheet.csv']:
            with self.subTest(name=name):
                out=self.folder/('batch-collision-'+name.replace('/','-'));target=out/name
                target.parent.mkdir(parents=True);target.write_bytes(b'keep this file')
                r=run_cli('batch',plans,'--out',out)
                self.assertNotEqual(r.returncode,0)
                self.assertEqual(target.read_bytes(),b'keep this file')
                self.assertFalse((out/'one/one.wav').exists())
    def test_source_audio_is_excluded_from_preview(self):
        source=self.folder/'noisy.mp4'
        result=subprocess.run([shutil.which('ffmpeg'),'-v','error','-i',str(INPUT),'-f','lavfi','-i',
                               'sine=frequency=800:sample_rate=48000:duration=2.3','-map','0:v:0','-map','1:a:0',
                               '-c:v','copy','-c:a','aac',str(source)],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        plan=self.plan();plan['source']='noisy.mp4';out=self.render(plan)
        result=subprocess.run([shutil.which('ffmpeg'),'-v','error','-i',str(out/'projectile.mp4'),
                               '-map','0:a:0','-f','f32le','-'],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        audio=np.frombuffer(result.stdout,dtype='<f4').reshape(-1,2)
        self.assertLess(np.max(np.abs(audio[:12000])),1e-6)
        self.assertGreater(np.max(np.abs(audio[66000:73000])),.1)
    def test_batch_produces_independent_outputs_and_archive(self):
        plans=self.folder/'plans';plans.mkdir()
        for name in ['one','two']:
            p=self.plan(name);p['source']=os.path.relpath(INPUT,plans)
            (plans/(name+'.json')).write_text(json.dumps(p),encoding='utf-8')
        out=self.folder/'batch';r=run_cli('batch',plans,'--out',out)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue((out/'one/one.wav').exists());self.assertTrue((out/'two/two.wav').exists())
        self.assertTrue((out/'delivery.zip').exists())
        with zipfile.ZipFile(out/'delivery.zip') as archive:
            self.assertIn('one/one.ogg',archive.namelist());self.assertIn('two/two.ogg',archive.namelist())
    def test_collect_downloads_media_once_and_records_sources(self):
        self.assertEqual(run_cli('--help').returncode,0)
        web=self.folder/'web';web.mkdir();shutil.copy2(self.make_gif(),web/'clip.gif');shutil.copy2(INPUT,web/'movie.mp4')
        (web/'index.html').write_text('<img src="clip.gif"><img src="clip.gif"><video src="movie.mp4"></video>',encoding='utf-8')
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(web)))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            out=self.folder/'refs';r=run_cli('collect',f'http://127.0.0.1:{server.server_port}/index.html','--out',out)
            self.assertEqual(r.returncode,0,r.stderr)
            manifest=json.loads((out/'sources.json').read_text(encoding='utf-8'))
            self.assertEqual(len(manifest['media']),2)
            self.assertEqual((out/'clip.gif').read_bytes(),(web/'clip.gif').read_bytes())
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main(verbosity=2)
