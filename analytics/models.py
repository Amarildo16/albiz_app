from django.db import models


class JoinedCompanyFeature(models.Model):
    id = models.AutoField(primary_key=True)
    company_nipt = models.CharField(max_length=64, unique=True)
    business_name = models.TextField(null=True, blank=True)
    legal_form = models.CharField(max_length=255, null=True, blank=True)
    subject_status = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=255, null=True, blank=True)
    registration_date = models.DateField(null=True, blank=True)
    registration_year = models.IntegerField(null=True, blank=True)
    source_row_count = models.IntegerField(default=0)
    app_source_row_count = models.IntegerField(default=0)
    qkb_source_row_count = models.IntegerField(default=0)
    active_procurement_count = models.IntegerField(default=0)
    cancelled_procurement_count = models.IntegerField(default=0)
    suspended_procurement_count = models.IntegerField(default=0)
    total_winner_value_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    active_total_winner_value_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    has_red_flags = models.BooleanField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'joined_company_features'

    def __str__(self):
        return self.business_name or self.company_nipt
