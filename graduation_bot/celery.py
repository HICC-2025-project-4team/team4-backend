# graduation_bot/celery.py

import os
from celery import Celery

# 1) Django settings 모듈 지정
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'graduation_bot.settings')

# 2) Celery 앱 인스턴스 생성
app = Celery('graduation_bot')

# 3) settings.py 에 있는 CELERY_* 설정을 app에 적용
app.config_from_object('django.conf:settings', namespace='CELERY')

# 4) INSTALLED_APPS 에 정의된 모든 tasks.py 를 자동으로 탐색
app.autodiscover_tasks()

# (선택) 디버깅용 테스트 태스크
@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
