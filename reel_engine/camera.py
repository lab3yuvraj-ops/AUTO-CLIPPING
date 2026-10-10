"""Offline camera easing on the final timeline; never blend source images."""
import numpy as np


def ease_camera(geometry,times,cuts=(),fps=30,duration=.8):
    """Smooth pan/tilt and logarithmic zoom within each source shot.

    A quintic ease derivative is a compact smoothing kernel: a step becomes
    an ease-in/out with zero velocity and acceleration at both ends. Offline
    lookahead avoids the persistent tracking lag of a causal low-pass filter.
    Source discontinuities and real scene cuts are independent reset boundaries.
    """
    if not geometry:return []
    values=np.asarray(geometry,dtype=float).copy()
    values[:,2]=np.log(values[:,2])
    radius=max(1,round(duration*fps/2))
    u=(np.arange(-radius,radius+1)+radius)/(2*radius)
    kernel=30*u*u*(1-u)*(1-u);kernel/=kernel.sum()
    boundaries=[0]
    for i in range(1,len(times)):
        if times[i]-times[i-1]>1.5/fps or times[i]<=times[i-1] or any(times[i-1]<c<=times[i]+.0001 for c in cuts):
            boundaries.append(i)
    boundaries.append(len(values))
    result=values.copy()
    for start,end in zip(boundaries,boundaries[1:]):
        for axis in range(3):
            padded=np.pad(values[start:end,axis],radius,mode='edge')
            result[start:end,axis]=np.convolve(padded,kernel,mode='valid')
    result[:,2]=np.exp(result[:,2])
    return result.tolist()
