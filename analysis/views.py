from rest_framework import generics, permissions, status
from rest_framework.response import Response
from transcripts.models import Transcript
from users.models import User
from .models import GraduationRequirement
from .serializers import GraduationStatusSerializer

import re
import unicodedata


# ---------------------------
# 유틸/공통
# ---------------------------
ROMAN = {"Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3", "Ⅳ": "4", "Ⅴ": "5",
         "Ⅵ": "6", "Ⅶ": "7", "Ⅷ": "8", "Ⅸ": "9"}

def _norm(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    for k, v in ROMAN.items():
        s = s.replace(k, v)
    s = re.sub(r"[·ㆍ\.\-_/]", "", s)
    s = re.sub(r"[\(\)\[\]\{\}\s]+", "", s)
    return s

def course_key_from_dict(d: dict) -> str:
    """비교 키: code 우선, 없으면 정규화된 name"""
    code = (d.get("code") or "").strip()
    if code:
        return code
    return _norm(d.get("name", ""))

def get_courses_from_parsed_data(parsed) -> list[dict]:
    """
    parsed_data 형태 안전하게 추출:
    - 권장: {"courses":[{...}]}
    - 과거: [{...}]
    """
    if not parsed:
        return []
    if isinstance(parsed, dict):
        return parsed.get("courses", []) or []
    if isinstance(parsed, list):
        return parsed
    return []

def get_valid_courses(transcript: Transcript) -> list[dict]:
    """F 성적 및 재수강 제외"""
    all_courses = get_courses_from_parsed_data(transcript.parsed_data)
    return [
        c for c in all_courses
        if c and (c.get("grade") != "F") and (not c.get("retake", False))
    ]

def distribute(total: int, n: int) -> list[int]:
    """총합을 n개로 최대한 고르게 분배 (드볼 영역 요구학점 추정용)"""
    if n <= 0:
        return []
    base = total // n
    rem = total % n
    arr = [base] * n
    for i in range(rem):
        arr[i] += 1
    return arr


# ---------------------------
# 핵심 분석 함수
# ---------------------------
def analyze_graduation(user_id: int):
    # 1) 유저
    user = User.objects.filter(id=user_id).first()
    if not user:
        return {"error": "사용자를 찾을 수 없습니다.", "status": 404}

    # 2) 성적표
    transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
    if not transcript or not transcript.parsed_data:
        return {"error": "성적표 데이터가 없습니다.", "status": 404}

    courses = get_valid_courses(transcript)

    # 3) 졸업요건 (입학년도 미사용: 전공으로만 매칭)
    requirement = GraduationRequirement.objects.filter(major=user.major).first()
    if not requirement:
        return {"error": "졸업 요건 데이터가 없습니다.", "status": 500}

    # 학점 합산
    total_credit = sum(c.get("credit", 0) for c in courses)
    major_credit = sum(c.get("credit", 0) for c in courses if "전공" in (c.get("type") or ""))
    general_credit = sum(c.get("credit", 0) for c in courses if "교양" in (c.get("type") or ""))
    drbol_credit = sum(c.get("credit", 0) for c in courses if "드볼" in (c.get("type") or ""))
    sw_credit = sum(c.get("credit", 0) for c in courses if ("sw" in (c.get("type") or "").lower() or "데이터활용" in (c.get("type") or "")))
    msc_credit = sum(c.get("credit", 0) for c in courses if "msc" in (c.get("type") or "").lower())
    special_general_credit = sum(c.get("credit", 0) for c in courses if "특성화교양" in (c.get("major_field") or ""))

    # 전공필수 미이수 (학기별 dict)
    must_list: list[dict] = requirement.major_must_courses or []
    completed_keys = {course_key_from_dict(c) for c in courses if c}
    missing_by_semester: dict[str, list[dict]] = {}
    for item in must_list:
        key = course_key_from_dict(item)
        if key in completed_keys:
            continue
        sem = item.get("semester") or "기타"
        missing_by_semester.setdefault(sem, []).append({
            "code": item.get("code", "") or "",
            "name": item.get("name", "") or ""
        })

    # ---------- 드볼: 7개 영역 중 서로 다른 6개 영역 + 총 18학점 ----------
    drbol_areas = [a.strip() for a in (requirement.drbol_areas or "").split(",") if a.strip()]
    required_areas_count = min(6, len(drbol_areas))  # 규칙: 7개 중 6개
    # 영역별 수강 과목 수
    area_course_count = {a: 0 for a in drbol_areas}
    for c in courses:
        mf = c.get("major_field") or ""
        if mf in area_course_count:
            area_course_count[mf] += 1
    covered_areas = [a for a, cnt in area_course_count.items() if cnt >= 1]
    covered_count = len(covered_areas)
    # 참고용: 아직 0과목인 영역 리스트
    missing_drbol_areas = [a for a in drbol_areas if area_course_count.get(a, 0) == 0]

    # ---------- 상태 판정 ----------
    status_flag = "complete"
    messages = []
    if total_credit < requirement.total_required:
        status_flag = "pending"; messages.append(f"총 학점 {requirement.total_required - total_credit}학점 부족")
    if major_credit < requirement.major_required:
        status_flag = "pending"; messages.append(f"전공 {requirement.major_required - major_credit}학점 부족")
    if general_credit < requirement.general_required:
        status_flag = "pending"; messages.append(f"교양필수 {requirement.general_required - general_credit}학점 부족")

    # ✅ 드볼: 총 학점(≥ 요구치) + 커버리지(서로 다른 영역 6개)
    if drbol_credit < requirement.drbol_required or covered_count < required_areas_count:
        status_flag = "pending"
        msg_parts = []
        if drbol_credit < requirement.drbol_required:
            msg_parts.append(f"드볼 학점 {requirement.drbol_required - drbol_credit}학점 부족")
        if covered_count < required_areas_count:
            msg_parts.append(f"드볼 영역 {covered_count}/{required_areas_count}")
        messages.append(" / ".join(msg_parts))

    if sw_credit < requirement.sw_required:
        status_flag = "pending"; messages.append(f"SW/데이터활용 {requirement.sw_required - sw_credit}학점 부족")
    if msc_credit < requirement.msc_required:
        status_flag = "pending"; messages.append(f"MSC {requirement.msc_required - msc_credit}학점 부족")
    if special_general_credit < requirement.special_general_required:
        status_flag = "pending"; messages.append(f"특성화교양 {requirement.special_general_required - special_general_credit}학점 부족")
    if any(missing_by_semester.values()):
        status_flag = "pending"; messages.append("전공 필수 미이수 존재")

    message = " / ".join(messages) if messages else "졸업 요건 충족"

    data = {
        "total_completed": total_credit,
        "total_required": requirement.total_required,

        "major_completed": major_credit,
        "major_required": requirement.major_required,

        "general_completed": general_credit,
        "general_required": requirement.general_required,

        "drbol_completed": drbol_credit,
        "drbol_required": requirement.drbol_required,

        "sw_completed": sw_credit,
        "sw_required": requirement.sw_required,

        "msc_completed": msc_credit,
        "msc_required": requirement.msc_required,

        "special_general_completed": special_general_credit,
        "special_general_required": requirement.special_general_required,

        # ✅ Serializer가 기대하는 형태 유지
        "missing_major_courses": missing_by_semester,
        "missing_drbol_areas": missing_drbol_areas,  # 이제 '모든 영역'이 아니라 '아직 0과목인 영역' 목록

        "graduation_status": status_flag,
        "message": message,
    }
    return {"data": data, "status": 200}



# ---------------------------
# View 클래스들 (기존 1~7 유지)
# ---------------------------
class GeneralCoursesView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])

        # 실제 필수 교양 목록은 DB에서 code/name으로 꺼내는 게 맞지만,
        # 현재 모델상 general_must_courses에 저장되어 있으면 해당 값 사용
        user = User.objects.filter(id=user_id).first()
        req = GraduationRequirement.objects.filter(major=user.major).first() if user else None
        general_must = [{"code": i.get("code",""), "name": i.get("name","")} for i in (req.general_must_courses or [])] if req else []

        data = result["data"]
        return Response({
            "필수교양": general_must,
            "이수여부": data["general_completed"] >= data["general_required"]
        }, status=status.HTTP_200_OK)


class MajorCoursesView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])

        # 전공필수(미이수)는 status에 담기고, 전공선택 목록은 필요시 확장
        data = result["data"]
        # 평탄화 예: 전체 미이수 리스트
        flat_missing = []
        for sem, lst in data["missing_major_courses"].items():
            for it in lst:
                flat_missing.append({"code": it["code"], "name": it["name"], "semester": sem})

        return Response({
            "전공필수": flat_missing,  # 미이수 리스트
            "전공선택": []            # TODO: 필요 시 requirement.major_selective_courses 기반 구현
        }, status=status.HTTP_200_OK)


class TotalCreditView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])
        return Response({"total_credit": result["data"]["total_completed"]})


class GeneralCreditView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])
        return Response({"general_credit": result["data"]["general_completed"]})


class MajorCreditView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])
        return Response({"major_credit": result["data"]["major_completed"]})


class StatisticsCreditView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])
        d = result["data"]
        general_rate = d["general_completed"] / d["general_required"] if d["general_required"] else 0
        major_rate = d["major_completed"] / d["major_required"] if d["major_required"] else 0
        return Response({"general_rate": general_rate, "major_rate": major_rate})


class StatusCreditView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = GraduationStatusSerializer

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])
        return Response(result["data"], status=status.HTTP_200_OK)


# ---------------------------
# ✅ 추가 8) 전체 필수 미이수 (major/general)
# ---------------------------
class RequiredMissingView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        # 공통
        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=404)
        transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
        if not transcript or not transcript.parsed_data:
            return Response({"error": "성적표 데이터가 없습니다."}, status=404)
        requirement = GraduationRequirement.objects.filter(major=user.major).first()
        if not requirement:
            return Response({"error": "졸업 요건 데이터가 없습니다."}, status=500)

        courses = get_valid_courses(transcript)
        completed_by_code = { (c.get("code") or "").strip() for c in courses if (c.get("code") or "").strip() }
        completed_by_name = { _norm(c.get("name")) for c in courses if c.get("name") }

        def is_completed(item: dict) -> bool:
            code = (item.get("code") or "").strip()
            if code:
                return code in completed_by_code
            return _norm(item.get("name")) in completed_by_name

        major_missing = [
            {"code": i.get("code","") or "", "name": i.get("name","") or "", "semester": (i.get("semester") or "기타")}
            for i in (requirement.major_must_courses or [])
            if not is_completed(i)
        ]

        general_missing = [
            {"code": i.get("code","") or "", "name": i.get("name","") or ""}
            for i in (requirement.general_must_courses or [])
            if not is_completed(i)
        ]

        return Response({
            "major_required_missing": major_missing,
            "general_required_missing": general_missing
        }, status=status.HTTP_200_OK)


# ---------------------------
# ✅ 추가 9) 미이수 드볼 영역
# ---------------------------
class DrbolMissingView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=404)
        transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
        if not transcript or not transcript.parsed_data:
            return Response({"error": "성적표 데이터가 없습니다."}, status=404)
        requirement = GraduationRequirement.objects.filter(major=user.major).first()
        if not requirement:
            return Response({"error": "졸업 요건 데이터가 없습니다."}, status=500)

        # 기준들
        areas = [a.strip() for a in (requirement.drbol_areas or "").split(",") if a.strip()]
        required_areas_count = 6                  # 규칙: 7개 중 6개 영역 커버
        required_credit_total = requirement.drbol_required  # 18

        # 수강 현황 집계
        courses = get_valid_courses(transcript)
        area_course_count = {a: 0 for a in areas}
        area_credit_sum   = {a: 0 for a in areas}
        drbol_credit_total = 0
        for c in courses:
            credit = c.get("credit", 0) or 0
            if "드볼" in (c.get("type") or ""):
                drbol_credit_total += credit
            mf = c.get("major_field") or ""
            if mf in area_course_count:
                area_course_count[mf] += 1
                area_credit_sum[mf]   += credit

        covered_areas = [a for a in areas if area_course_count[a] >= 1]
        missing_areas = [a for a in areas if area_course_count[a] == 0]

        rows = []
        for a in areas:
            rows.append({
                "area": a,
                "covered": area_course_count[a] >= 1,
                "courses_count": area_course_count[a],
                "completed_credit": area_credit_sum[a],
            })

        return Response({
            "areas": rows,
            "areas_required": required_areas_count,                      # 최소 커버해야 하는 영역 수(6)
            "areas_covered": len(covered_areas),
            "areas_remaining": max(0, required_areas_count - len(covered_areas)),
            "missing_areas": missing_areas,
            "total_credit_completed": drbol_credit_total,                # 드볼 총 이수 학점
            "total_credit_required": required_credit_total,              # 18
            "credit_remaining": max(0, required_credit_total - drbol_credit_total),
        }, status=status.HTTP_200_OK)



# ---------------------------
# ✅ 추가 10) 필수 과목 로드맵
# ---------------------------
class RequiredRoadmapView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=404)
        transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
        if not transcript or not transcript.parsed_data:
            return Response({"error": "성적표 데이터가 없습니다."}, status=404)
        requirement = GraduationRequirement.objects.filter(major=user.major).first()
        if not requirement:
            return Response({"error": "졸업 요건 데이터가 없습니다."}, status=500)

        courses = get_valid_courses(transcript)
        # 완료 맵: code/name -> taken_semester
        complete_map: dict[str, str] = {}
        for c in courses:
            key = course_key_from_dict(c)
            if key and key not in complete_map:
                complete_map[key] = c.get("semester") or None

        def build(items: list[dict]) -> list[dict]:
            rows = []
            for it in (items or []):
                key = course_key_from_dict(it)
                taken = complete_map.get(key)
                rows.append({
                    "code": it.get("code","") or "",
                    "name": it.get("name","") or "",
                    "planned_semester": it.get("semester") or None,
                    "completed": taken is not None,
                    "taken_semester": taken
                })
            return rows

        major_roadmap = build(requirement.major_must_courses)
        general_roadmap = build(requirement.general_must_courses)

        return Response({
            "major_required_roadmap": major_roadmap,
            "general_required_roadmap": general_roadmap
        }, status=status.HTTP_200_OK)