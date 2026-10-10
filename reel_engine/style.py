"""The approved Reel output contract; versioned in each new job."""
STYLE='approved-horror-v1'

def approved_config(preferences):
    return {**preferences,'style_preset':STYLE,'font':'Creepster','caption_y':1420,
            'caption_position_locked':True,'camera_easing_seconds':1.2,
            'min_duration':30,'max_duration':min(60,preferences.get('max_duration',60)),
            'auto_publish':False,'approval_required':True}

def apply_style(edit,tracking,config):
    if config.get('style_preset')!=STYLE:return edit,tracking
    edit={**edit,'caption_positions':[]}
    cuts=tracking.get('camera_cuts',[s['t'] for s in tracking.get('samples',[]) if s.get('cut')])
    tracking={**tracking,'mode':'auto','composition':'fill','camera_smoothing':True,
              'camera_easing_seconds':1.2,'camera_cuts':cuts,'style_preset':STYLE}
    return edit,tracking
