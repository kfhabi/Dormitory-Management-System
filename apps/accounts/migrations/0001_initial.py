import apps.accounts.models
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Account',
            fields=[
                ('id', apps.accounts.models.UnsignedBigAutoField(primary_key=True, serialize=False)),
                ('email', models.EmailField(db_collation='utf8mb4_0900_as_cs', max_length=254, unique=True)),
                ('password', models.CharField(db_column='password_hash', max_length=255)),
                ('role', models.CharField(choices=[('STUDENT', 'Sinh viên'), ('MANAGER', 'Ban quản lý'), ('ADMIN', 'Quản trị viên')], default='STUDENT', max_length=10)),
                ('status', models.CharField(choices=[('ACTIVE', 'Hoạt động'), ('LOCKED', 'Đã khóa')], default='ACTIVE', max_length=6)),
                ('must_change_password', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Tài khoản',
                'db_table': 'accounts',
                'managed': False,
            },
        ),
    ]
