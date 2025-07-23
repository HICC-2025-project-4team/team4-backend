from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    student_id  = models.CharField(max_length=20, unique=True)
    full_name   = models.CharField(max_length=100)
    entry_year  = models.PositiveSmallIntegerField()
    major       = models.CharField(max_length=100)

    USERNAME_FIELD = 'student_id'
    REQUIRED_FIELDS = ['username', 'full_name', 'entry_year', 'major']
