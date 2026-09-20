from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('deals', '0013_product_canonical_aliases')]
    operations = [migrations.CreateModel(
        name='DealAvailability',
        fields=[
            ('deal', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, serialize=False, related_name='availability', to='deals.deal')),
            ('state', models.CharField(max_length=12, default='unknown', choices=[('unknown', '미확인'), ('active', '진행'), ('ended', '종료'), ('deleted', '원문 삭제')])),
            ('last_outcome', models.CharField(max_length=12, default='unknown')),
            ('evidence', models.CharField(max_length=200, blank=True, default='')),
            ('checked_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('ended_at', models.DateTimeField(null=True, blank=True)),
            ('missing_since', models.DateTimeField(null=True, blank=True)),
            ('missing_count', models.PositiveSmallIntegerField(default=0)),
            ('next_check_at', models.DateTimeField(default=django.utils.timezone.now, db_index=True)),
        ], options={'db_table': 'deal_availability'},
    )]
