"""Submit this interface as a single agent.py, implementing your own strategy."""
def choose(observation, memory):
    assert observation['version']=='gem-arena-2.0'
    # Every entry is fully legal, including payment/discard/noble choices.
    # A turn may invoke choose again for phase='discard' or phase='noble'.
    return {'action':0,'memory':None}
