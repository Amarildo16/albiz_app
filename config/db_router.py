class AlbizDatabaseRouter:
    core_app_labels = {'admin', 'auth', 'contenttypes', 'sessions', 'messages'}
    data_app_labels = {'analytics'}

    def db_for_read(self, model, **hints):
        if model._meta.app_label in self.data_app_labels:
            return 'data'
        if model._meta.app_label in self.core_app_labels:
            return 'default'
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label in self.data_app_labels:
            return 'data'
        if model._meta.app_label in self.core_app_labels:
            return 'default'
        return None

    def allow_relation(self, obj1, obj2, **hints):
        labels = {obj1._meta.app_label, obj2._meta.app_label}
        if labels <= self.core_app_labels or labels <= self.data_app_labels:
            return True
        if labels & self.data_app_labels:
            return False
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.core_app_labels:
            return db == 'default'
        if app_label in self.data_app_labels:
            return False
        return db == 'default'
