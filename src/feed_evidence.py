"""Conservative observation of U1 feeder channels, not spool identification."""


class FeedEvidence:
    def __init__(self):
        self.channels = [None] * 4
        self.insertions = [False] * 4
        self.runouts = [False] * 4
        self.coverage_lost = [False] * 4
        self.valid = True

    def apply(self, status):
        if not isinstance(status, dict):
            self.valid = False
            return
        for name in ('filament_feed left', 'filament_feed right'):
            if name not in status:
                continue
            channels = status[name]
            if not isinstance(channels, dict):
                self.valid = False
                continue
            for key, update in channels.items():
                if key not in ('extruder0', 'extruder1', 'extruder2', 'extruder3') or not isinstance(update, dict):
                    self.valid = False
                    continue
                head = int(key[-1])
                prior = self.channels[head]
                value = dict(prior) if isinstance(prior, dict) else {}
                for field in ('module_exist', 'disable_auto', 'filament_detected'):
                    if field in update:
                        if type(update[field]) is not bool:
                            self.valid = False
                            continue
                        value[field] = update[field]
                if isinstance(prior, dict) and 'filament_detected' in update and type(update['filament_detected']) is bool:
                    previous = prior.get('filament_detected')
                    if previous is True and update['filament_detected'] is False:
                        self.runouts[head] = True
                    if previous is False and update['filament_detected'] is True:
                        self.insertions[head] = True
                if value.get('module_exist') is False or value.get('disable_auto') is True:
                    self.coverage_lost[head] = True
                self.channels[head] = value

    def report(self):
        channels = [dict(x) if x is not None else None for x in self.channels]
        # Only a presently enabled sensor can be used as supporting evidence.
        covered = [bool(isinstance(x, dict) and x.get('module_exist') is True and x.get('disable_auto') is False
                        and type(x.get('filament_detected')) is bool and not self.coverage_lost[i])
                   for i, x in enumerate(channels)]
        return {'valid': self.valid, 'covered': covered, 'runouts': list(self.runouts),
                'insertions': list(self.insertions), 'channels': channels,
                'proves_spool_identity': False}

    def for_new_job(self):
        new = FeedEvidence()
        new.channels = [dict(x) if isinstance(x, dict) else None for x in self.channels]
        new.valid = self.valid
        new.coverage_lost = [not (isinstance(x, dict) and x.get('module_exist') is True
                                  and x.get('disable_auto') is False and type(x.get('filament_detected')) is bool)
                             for x in new.channels]
        return new
