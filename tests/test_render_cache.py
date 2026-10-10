from pathlib import Path
from reel_engine import render


def test_lossless_cache_reuses_caption_revision_but_rejects_changed_pixels(monkeypatch,tmp_path):
    source=tmp_path/'source.bin';source.write_bytes(b'original source')
    path=tmp_path/'edited.mkv';calls=[]
    def encode(src,edit,dst):
        calls.append(src.read_bytes());dst.write_bytes(src.read_bytes()+b'encoded')
    monkeypatch.setattr(render,'_edit_source_uncached',encode)
    edit={'segments':[{'source_start':1,'source_end':4,'output_start':0,'output_end':3}],'words':[{'roman':'hello'}]}
    assert render.edit_source(source,edit,path) is False
    edit['words'][0]['roman']='corrected caption'
    assert render.edit_source(source,edit,path) is True
    # Same file length is not enough to establish identical media.
    source.write_bytes(b'modified source')
    assert render.edit_source(source,edit,path) is False
    path.write_bytes(b'corrupted output')
    assert render.edit_source(source,edit,path) is False
    assert len(calls)==3
