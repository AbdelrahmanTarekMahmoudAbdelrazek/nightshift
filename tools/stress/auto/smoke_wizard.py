# Night Shift lab smoke test (28 Oct): can the lab reach and drive the Wizard editor without the gallery picker?


@scenario('nightshift', 'auto', 'smoke', 'nodraft')
def smoke_wizard(ed, r):
    """Smoke: Quick Cut with 3 clips -> template Edit -> Advanced Edit -> Wizard; select, drag 0->1, delete clip 0."""
    ed.open_wizard(3)
    n0 = len(ed.wizard_thumbs())
    ed.log(f'    smoke: {n0} thumbnails after open')
    ed.wizard_select(1)
    ed.require_log(r'MsgSeekVideo', timeout=10, why='selecting a thumbnail seeks the player')
    ed.wizard_drag(0, 1)
    ed.require_log(r'MsgSortMedia', timeout=10, why='dragging a thumbnail sends sortMedia')
    ed.wizard_delete(0)
    ed.require_log(r'Detach|MsgDeleteMedia', timeout=15, why='Wizard delete detaches the clip')
    ed.log(f'    smoke: {len(ed.wizard_thumbs())} thumbnails after delete (was {n0})')
