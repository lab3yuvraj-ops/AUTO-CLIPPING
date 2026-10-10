"""Real-media regression for fractional seek pre-roll and the last frame."""
import shutil
import subprocess
import cv2
import pytest
from reel_engine.render import edit_source, probe


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg is required')
def test_fractional_seek_has_zero_start_and_complete_frame_sequence(tmp_path):
    source = tmp_path / 'source.mkv'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                    'testsrc2=size=160x90:rate=30:duration=4',
                    '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=4',
                    '-c:v','ffv1','-c:a','pcm_s16le',str(source)], check=True)
    edited = tmp_path / 'edited.mkv'
    edit_source(source, {'segments':[{'source_start':.77,'source_end':3.07}]}, edited)
    data = probe(edited)
    video = next(s for s in data['streams'] if s['codec_type']=='video')
    assert float(video['start_time']) == 0
    cap = cv2.VideoCapture(str(edited))
    count = 0
    while cap.read()[0]:
        count += 1
    cap.release()
    assert count == 69  # 2.3 seconds at 30 fps, including the last output frame.
