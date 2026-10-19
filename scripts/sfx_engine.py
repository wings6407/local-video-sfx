"""Deterministic, isolated procedural Foley primitives (no remote services)."""
from pathlib import Path
import math
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly

RATE = 48000
TYPES = {'whoosh','impact','mud','scatter','rotor','suction','bubble','sample'}

def _time(duration):
    return np.arange(max(1,round(duration*RATE)),dtype=np.float64)/RATE

def _fade(samples,attack=.002,release=.015):
    x=samples.copy();a=min(len(x)//2,round(attack*RATE));b=min(len(x)//2,round(release*RATE))
    if a:x[:a]*=np.sin(np.linspace(0,np.pi/2,a))**2
    if b:x[-b:]*=np.cos(np.linspace(0,np.pi/2,b))**2
    return x

def _noise(duration,low,high,rng):
    if not 0<low<high<RATE/2:raise ValueError('Noise band must satisfy 0 < low_hz < high_hz < 24000')
    x=sosfilt(butter(3,[low,high],btype='bandpass',fs=RATE,output='sos'),rng.normal(size=len(_time(duration))))
    return x/max(np.sqrt(np.mean(x*x)),1e-12)

def _hit(duration,material,rng):
    choices={
      'metal':([413,897,1613,2767],[.032,.055,.036,.019],420,5700,.40),
      'blade':([523,1187,2239,3793],[.026,.047,.032,.015],600,6500,.35),
      'ceramic':([723,1433,2639],[.017,.023,.013],260,3600,.42),
      'body':([83,147,239],[.020,.014,.009],60,1200,.14),
      'grain':([431,1189],[.006,.004],700,3900,.10),
    }
    if material not in choices:raise ValueError('Unknown impact material: '+str(material))
    freqs,decays,low,high,resonance=choices[material];t=_time(duration)
    modes=sum(np.sin(2*np.pi*f*t+rng.uniform(-.12,.12))*np.exp(-t/decay) for f,decay in zip(freqs,decays))/len(freqs)
    transient=_noise(duration,low,high,rng)*np.exp(-t/(.022 if material=='body' else .013))
    return _fade(transient*.58+modes*resonance,.0007,.02)

def synthesize(kind,duration,params,rng,base_dir):
    """Return mono samples, or stereo samples for a supplied local audio file."""
    t=_time(duration);p=t/duration
    if kind=='whoosh':
        low=float(params.get('low_hz',260));high=float(params.get('high_hz',4800))
        power=float(params.get('power',2.2))
        if not math.isfinite(power) or power<=0:raise ValueError('Whoosh power must be positive')
        env=np.maximum(0,np.sin(np.pi*np.minimum(p,1)))**power
        tail_high=low+(high-low)*.35
        return _fade((_noise(duration,low,high,rng)*(1-p*.5)+_noise(duration,low,tail_high,rng)*p*.4)*env)
    if kind=='impact':return _hit(duration,params.get('material','body'),rng)
    if kind=='mud':
        body=np.sin(2*np.pi*(125*t+60*.022*(1-np.exp(-t/.022))))*np.exp(-t/.029)
        wet=_noise(duration,260,2700,rng)*np.exp(-t/.061)*(.28+.72*np.sin(2*np.pi*(48*t+39*t*t))**2)
        dull=_noise(duration,70,780,rng)*np.exp(-t/.043)
        return _fade(np.tanh(.27*body+.22*dull+.23*wet),.001,.025)
    if kind=='scatter':
        count=params.get('count',10)
        if not isinstance(count,int) or not 1<=count<=100:raise ValueError('Scatter count must be an integer from 1 to 100')
        result=np.zeros(len(t))
        delays=np.sort(rng.uniform(min(.008,duration/8),max(duration*.85,.009),count))
        for delay in delays:
            start=min(len(result)-1,round(delay*RATE));length=min(.055,(len(result)-start)/RATE)
            grain=_hit(length,params.get('material','grain'),rng)*np.exp(-delay/(duration*.48))
            result[start:start+len(grain)]+=grain
        return _fade(result,.0005,.010)
    if kind=='rotor':
        env=np.minimum(1,t/.12)*np.minimum(1,(duration-t)/.18)
        phase=2*np.pi*(8*t+9*t*t/duration)
        blades=.18+.82*np.maximum(0,np.sin(phase))**2
        turbulent=_noise(duration,95,2300,rng)*blades+_noise(duration,800,5500,rng)*.16
        mechanical=np.sin(2*np.pi*(71*t+48*t*t/duration))*.07+np.sin(2*np.pi*(137*t+70*t*t/duration))*.035
        return _fade((turbulent+mechanical)*env)
    if kind=='suction':
        env=np.minimum(1,t/.13)*np.minimum(1,(duration-t)/.15)
        churning=_noise(duration,85,1800,rng)*(.5+.5*np.sin(2*np.pi*(7*t+3*t*t/duration))**2)
        liquid=_noise(duration,600,4300,rng)*(.18+.82*np.sin(2*np.pi*17*t)**6)*.22
        return _fade((churning+liquid)*env)
    if kind=='bubble':
        f=rng.uniform(170,300)
        return _fade((np.sin(2*np.pi*(f*t+f*.012*(1-np.exp(-t/.012))))*.48+_noise(duration,160,1300,rng)*.20)*np.exp(-t/.018),.001,.012)
    if kind=='sample':
        file=params.get('file')
        if not file:raise ValueError('A sample event requires params.file')
        source=(Path(base_dir)/file).resolve()
        audio,rate=sf.read(source,always_2d=True,dtype='float64')
        if audio.shape[1] not in (1,2):raise ValueError('A sample must be mono or stereo')
        if not np.isfinite(audio).all():raise ValueError('A sample contains non-finite values')
        offset=float(params.get('offset',0))
        if not math.isfinite(offset) or offset<0:raise ValueError('Sample offset must be nonnegative')
        audio=audio[round(offset*rate):]
        if rate!=RATE:
            gcd=math.gcd(rate,RATE);audio=resample_poly(audio,RATE//gcd,rate//gcd,axis=0)
        result=np.zeros((len(t),audio.shape[1]));count=min(len(result),len(audio));result[:count]=audio[:count]
        for channel in range(result.shape[1]):result[:,channel]=_fade(result[:,channel])
        return result[:,0] if result.shape[1]==1 else result
    raise ValueError('Unknown event type: '+str(kind))

def mix_events(events,duration,seed,base_dir,peak_dbfs=-2):
    """Mix only the declared event windows, with one common gain for all stems."""
    if not math.isfinite(peak_dbfs) or not -30<=peak_dbfs<=-1.5:raise ValueError('peak_dbfs must be from -30 to -1.5')
    length=round(duration*RATE);rng=np.random.default_rng(seed)
    stems={};allowed=np.zeros(length,bool)
    for event in events:
        samples=synthesize(event['type'],event['duration'],event.get('params',{}),rng,base_dir)
        if not np.isfinite(samples).all():raise ValueError('Generated non-finite samples')
        start=round(event['at']*RATE);count=min(len(samples),length-start)
        angle=(event.get('pan',0)+1)*np.pi/4;gain=event.get('gain',1)
        stem=np.zeros((length,2))
        if samples.ndim==1:
            stem[start:start+count,0]=samples[:count]*gain*np.cos(angle)
            stem[start:start+count,1]=samples[:count]*gain*np.sin(angle)
        else:
            stem[start:start+count]=samples[:count]*gain*np.array([np.cos(angle),np.sin(angle)])*np.sqrt(2)
        stems[event['id']]=stem;allowed[start:start+count]=True
    mix=sum(stems.values(),np.zeros((length,2)))
    peak=max([np.max(np.abs(mix),initial=0),*(np.max(np.abs(x),initial=0) for x in stems.values())])
    scale=10**(peak_dbfs/20)/peak if peak>0 else 1.
    true_peak=np.max(np.abs(resample_poly(mix*scale,4,1,axis=0)),initial=0)
    if true_peak>10**(-1.5/20):scale*=10**(-1.5/20)/true_peak
    return mix*scale,{key:audio*scale for key,audio in stems.items()},allowed
