from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('deals', '0012_product_identity')]
    operations = [
        migrations.AddField('product', 'is_active', models.BooleanField(default=True, db_default=True, verbose_name='목록에 표시')),
        migrations.AddField('product', 'merged_into', models.ForeignKey(
            'deals.product', on_delete=django.db.models.deletion.PROTECT, null=True, blank=True,
            related_name='previous_identities', editable=False)),
    ]
