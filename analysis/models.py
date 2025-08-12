from django.db import models

class GraduationRequirement(models.Model):
    major = models.CharField(max_length=100)        # 학과명
    year = models.PositiveSmallIntegerField()       # 입학년도 (예: 2025) - 쿼리에는 사용하지 않음(호환 유지)

    # 총 학점 요건
    total_required = models.IntegerField(default=132)
    major_required = models.IntegerField(default=50)
    general_required = models.IntegerField(default=8)
    drbol_required = models.IntegerField(default=18)
    special_general_required = models.IntegerField(default=3)
    sw_required = models.IntegerField(default=9)
    msc_required = models.IntegerField(default=23)

    # 전공 필수 / 전공 선택
    # 각 아이템 예시: {"code":"101510","name":"컴퓨터구조","semester":"3-1","aliases":["컴구"]}
    major_must_courses = models.JSONField(
        help_text="전공필수 과목 리스트(JSON). 각 항목: {code, name, semester?, aliases?}"
    )
    major_selective_courses = models.JSONField(
        help_text="전공선택 과목 리스트(JSON). 각 항목: {code, name, semester?, aliases?}",
        null=True, blank=True
    )

    # 교양 필수 / 교양 선택 / 특성화교양 / SW / MSC
    # 각 리스트의 항목 포맷은 동일: {code, name, semester?, aliases?}
    general_must_courses = models.JSONField(
        help_text="교양필수 과목 리스트(JSON). 각 항목: {code, name, semester?, aliases?}",
        null=True, blank=True
    )
    general_selective_courses = models.JSONField(
        help_text="일반선택(교양선택) 과목 리스트(JSON). 각 항목: {code, name, semester?, aliases?}",
        null=True, blank=True
    )
    special_general_courses = models.JSONField(
        help_text="특성화교양 과목 리스트(JSON). 각 항목: {code, name, semester?, aliases?}",
        null=True, blank=True
    )
    sw_courses = models.JSONField(
        help_text="SW/데이터활용역량 과목 리스트(JSON). 각 항목: {code, name, semester?, aliases?}",
        null=True, blank=True
    )
    msc_courses = models.JSONField(
        help_text="MSC 과목 리스트(JSON). 각 항목: {code, name, semester?, aliases?}",
        null=True, blank=True
    )

    # 드볼 (레거시 + 신규 규칙)
    drbol_areas = models.TextField(
        help_text="(레거시) 드볼 영역 이름(콤마 구분). 예: '인문과예술,사회와문화,자연과기술'",
        null=True, blank=True
    )
    # 새 규칙: 영역별 요구학점 명시
    # 예: [{"area":"인문과예술","required_credit":6},{"area":"사회와문화","required_credit":6},{"area":"자연과기술","required_credit":6}]
    drbol_rules = models.JSONField(
        help_text="드볼 영역 규칙(JSON). 각 항목: {area, required_credit}",
        null=True, blank=True
    )
    # 영역별 실제 과목(선택): { "인문과예술": [{code,name,...}], "사회와문화": [...] }
    drbol_courses = models.JSONField(
        help_text="드볼 영역별 과목 리스트(JSON). 키=area, 값=과목 배열(각 항목: {code, name, semester?, aliases?})",
        null=True, blank=True
    )

    class Meta:
        unique_together = ('major', 'year')  # 연도는 호환 위해 유지(쿼리에서는 major만 사용 가능)

    def __str__(self):
        return f"{self.major} {self.year}학번 졸업 요건"