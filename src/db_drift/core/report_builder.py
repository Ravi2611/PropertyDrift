class ReportBuilder:
    def __init__(self):
        self.report = {
            "summary": {"critical": 0, "warning": 0, "info": 0},
            "mysql": {},
            "mongo": {},
            "errors": []
        }

    def add_mysql_results(self, results):
        self.report['mysql'] = results
        self._update_summary(results)

    def add_mongo_results(self, results):
        self.report['mongo'] = results
        self._update_summary(results)

    def add_errors(self, errors):
        self.report['errors'].extend(errors)

    def _update_summary(self, results):
        for db_name, drifts in results.items():
            for drift in drifts:
                sev = drift['severity'].lower()
                if sev in self.report['summary']:
                    self.report['summary'][sev] += 1

    def build(self):
        return self.report
