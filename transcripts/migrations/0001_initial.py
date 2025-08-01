# Generated by Django 5.2.4 on 2025-07-27 12:59

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Transcript',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='transcripts/')),
                ('status', models.CharField(choices=[('PENDING', '대기'), ('PROCESSING', '처리 중'), ('DONE', '완료'), ('ERROR', '오류')], default='PENDING', max_length=10)),
                ('parsed', models.JSONField(blank=True, null=True)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
