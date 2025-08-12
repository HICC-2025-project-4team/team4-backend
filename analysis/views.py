from rest_framework import generics, permissions, status
from rest_framework.response import Response
from transcripts.models import Transcript
from users.models import User
from .models import GraduationRequirement
from .serializers import GraduationStatusSerializer

# ---------------------------
# 유틸/공통 (코드 전용 비교)
# ---------------------------
import re
import unicodedata
from typing import Any, Dict, List

ROMAN = {"Ⅰ":"1","Ⅱ":"2","Ⅲ":"3","Ⅳ":"4","Ⅴ":"5","Ⅵ":"6","Ⅶ":"7","Ⅷ":"8","Ⅸ":"9"}

def _norm(s: str | None) -> str:
    """(이름 비교가 필요할 때만 사용; 현재 키 비교는 code 전용)"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    for k, v in ROMAN.items():
        s = s.replace(k, v)
    s = re.sub(r"[·ㆍ\.\-_/]", "", s)
    s = re.sub(r"[\(\)\[\]\{\}\s]+", "", s)
    return s

def norm_code(x) -> str:
    """학수번호 정규화: 숫자만 남기고 6자리 zero-pad"""
    s = re.sub(r"\D", "", str(x or ""))
    return s.zfill(6) if s else ""

def course_key_from_dict(d: Dict[str, Any]) -> str:
    """비교 키: code만 사용 (이름 fallback 제거)"""
    return norm_code(d.get("code"))

def get_courses_from_parsed_data(parsed) -> List[Dict[str, Any]]:
    """parsed(_data) 안전 추출"""
    if not parsed:
        return []
    if isinstance(parsed, dict):
        return parsed.get("courses", []) or []
    if isinstance(parsed, list):
        return parsed
    return []

def get_valid_courses(transcript):
    payload = transcript.parsed_data
    all_courses = payload.get("courses", []) if isinstance(payload, dict) else (payload or [])
    return [
        c for c in all_courses
        if c and str(c.get("grade","")).upper() != "F" and not c.get("retake", False)
    ]


def distribute(total: int, n: int) -> List[int]:
    """총합을 n개로 고르게 분배"""
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
    total_credit = sum(int(c.get("credit", 0) or 0) for c in courses)
    major_credit = sum(int(c.get("credit", 0) or 0) for c in courses if "전공" in (c.get("type") or ""))
    general_credit = sum(int(c.get("credit", 0) or 0) for c in courses if "교양" in (c.get("type") or ""))
    drbol_credit = sum(int(c.get("credit", 0) or 0) for c in courses if "드볼" in (c.get("type") or ""))
    sw_credit = sum(int(c.get("credit", 0) or 0) for c in courses if ("sw" in (c.get("type") or "").lower() or "데이터활용" in (c.get("type") or "")))
    msc_credit = sum(int(c.get("credit", 0) or 0) for c in courses if "msc" in (c.get("type") or "").lower())
    special_general_credit = sum(int(c.get("credit", 0) or 0) for c in courses if "특성화교양" in (c.get("major_field") or ""))

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

    # ---------- 드볼: 7개 영역 중 서로 다른 6개 영역 + 총 18학점(예외: 17학점 + 2학점 영역 1개) ----------
    drbol_areas = [a.strip() for a in (requirement.drbol_areas or "").split(",") if a.strip()]
    required_areas_count = min(6, len(drbol_areas))  # 규칙: 7개 중 6개

    # 영역별 수강 과목 수/학점
    area_course_count = {a: 0 for a in drbol_areas}
    area_credits = {a: 0 for a in drbol_areas}
    total_dvbol_credit = 0

    for c in courses:
        mf = (c.get("major_field") or "").strip()
        if mf in area_course_count:
            credit_val = int(c.get("credit") or 0)
            area_course_count[mf] += 1
            area_credits[mf] += credit_val
            total_dvbol_credit += credit_val

    # 커버한/미커버 영역
    covered_areas = [a for a, cnt in area_course_count.items() if cnt >= 1]
    covered_count = len(covered_areas)
    missing_drbol_areas = [a for a in drbol_areas if area_course_count.get(a, 0) == 0]

    # 17학점 예외: "총 17학점" 이고 "커버 영역 중 적어도 한 영역의 합계가 2학점"이면 OK
    has_two_credit_area = any(area_credits.get(a, 0) == 2 for a in covered_areas)

    coverage_ok = covered_count >= required_areas_count
    credit_ok = (total_dvbol_credit >= 18) or (total_dvbol_credit == 17 and has_two_credit_area)

    # 응답용 보조 값들
    areas_remaining = max(required_areas_count - covered_count, 0)
    credit_remaining = max(0, 18 - total_dvbol_credit) if not (total_dvbol_credit == 17 and has_two_credit_area) else 0

    # 영역별 상세(프런트 시각화용)
    areas_detail = [
        {
            "area": a,
            "covered": area_course_count[a] >= 1,
            "courses_count": area_course_count[a],
            "completed_credit": area_credits[a],
        }
        for a in drbol_areas
    ]

    dvbol_result = {
        "areas": areas_detail,
        "areas_required": required_areas_count,
        "areas_covered": covered_count,
        "areas_remaining": areas_remaining,
        "missing_areas": missing_drbol_areas,
        "total_credit_completed": total_dvbol_credit,
        "total_credit_required": 18,
        "credit_remaining": credit_remaining,
        "coverage_ok": coverage_ok,
        "credit_ok": credit_ok,
        "status": coverage_ok and credit_ok,  # 최종 판정
    }

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
    if (total_dvbol_credit < requirement.drbol_required) or (covered_count < required_areas_count):
        status_flag = "pending"
        msg_parts = []
        if total_dvbol_credit < requirement.drbol_required:
            msg_parts.append(f"드볼 학점 {requirement.drbol_required - total_dvbol_credit}학점 부족")
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

        "drbol_completed": total_dvbol_credit,  # 영역 합으로 일관 표기
        "drbol_required": requirement.drbol_required,

        "sw_completed": sw_credit,
        "sw_required": requirement.sw_required,

        "msc_completed": msc_credit,
        "msc_required": requirement.msc_required,

        "special_general_completed": special_general_credit,
        "special_general_required": requirement.special_general_required,

        # ✅ Serializer가 기대하는 형태 유지
        "missing_major_courses": missing_by_semester,
        "missing_drbol_areas": missing_drbol_areas,

        "graduation_status": status_flag,
        "message": message,
    }
    return {"data": data, "status": 200}


# ---------------------------
# View 클래스들 (1~7)
# ---------------------------
class GeneralCoursesView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])

        user = User.objects.filter(id=user_id).first()
        req = GraduationRequirement.objects.filter(major=user.major).first() if user else None
        if not req:
            return Response({"error": "졸업 요건 데이터가 없습니다."}, status=500)

        transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
        courses = get_valid_courses(transcript)

        # 내가 실제 수강한 코드 집합 (정규화)
        taken_codes = { norm_code(c.get("code")) for c in courses if c.get("code") }

        # 1) 이름-코드 매핑, 2) 이름(그룹키)별 코드 묶기
        def group_key(name: str) -> str:
            # '전공기초영어(1)' -> '전공기초영어' 로 묶기 (괄호 숫자 제거)
            if not name:
                return ""
            m = re.match(r"^(.*?)(?:\(\s*\d+\s*\))$", name.strip())
            return (m.group(1) if m else name.strip())

        name_by_code: dict[str, str] = {}
        groups: dict[str, set[str]] = {}
        for i in (req.general_must_courses or []):
            code = norm_code(i.get("code"))
            name = (i.get("name") or "").strip()
            if not code or not name:
                continue
            name_by_code[code] = name
            groups.setdefault(group_key(name), set()).add(code)

        # 각 그룹에서 실제로 '수강한 코드'만 수집
        completed_items = []
        missing_groups = []
        for base, codes in groups.items():
            hit = codes & taken_codes
            if hit:
                # 실제 들은 코드만 응답 리스트에 포함
                for code in sorted(hit):
                    completed_items.append({
                        "code": code,
                        "name": name_by_code.get(code, base)
                    })
            else:
                missing_groups.append(base)

        is_completed_all = (len(missing_groups) == 0) if groups else False

        return Response({
            "필수교양": completed_items,   # ✅ 실제로 들은 필수 교양만 노출
            "이수여부": is_completed_all
            # 디버깅용으로 보고 싶으면 "부족그룹": missing_groups 를 잠깐 추가해도 좋아요.
        }, status=status.HTTP_200_OK)



class MajorCoursesView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])

        user = User.objects.filter(id=user_id).first()
        req = GraduationRequirement.objects.filter(major=user.major).first() if user else None
        if not req:
            return Response({"error": "졸업 요건 데이터가 없습니다."}, status=500)

        transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
        courses = get_valid_courses(transcript)
        taken_codes = { norm_code(c.get("code")) for c in courses if (c.get("code") or "").strip() }

        def completed_from(require_list):
            rows = []
            for it in (require_list or []):
                code = norm_code(it.get("code"))
                if code and code in taken_codes:
                    rows.append({"code": code, "name": it.get("name","")})
            return rows

        return Response({
            "전공필수": completed_from(req.major_must_courses),
            "전공선택": completed_from(req.major_selective_courses),
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
        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=404)

        transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
        if not transcript or not (getattr(transcript, "parsed_data", None) or getattr(transcript, "parsed", None)):
            return Response({"general_credit": 0}, status=200)

        # 졸업요건에서 드볼 영역명 리스트 가져오기
        req = GraduationRequirement.objects.filter(major=user.major).first()
        drbol_areas = []
        if req and req.drbol_areas:
            drbol_areas = [a.strip() for a in req.drbol_areas.split(",") if a.strip()]

        # ✅ 일관성: 재수강/F 제외 후 합산
        courses = get_valid_courses(transcript)
        general_credit = 0

        for c in courses:
            ctype  = (c.get("type") or "").strip()                # 예: 교양 / 드볼 / 특성화교양 / 전공
            mfield = (c.get("major_field") or "").strip()         # 예: 교양필수 / 교양선택 / 드볼 영역명 등
            credit = int(c.get("credit") or 0)

            is_general_type  = ctype in {"교양", "드볼", "특성화교양"}
            is_general_field = mfield in {"교양필수", "교양선택", "특성화교양"} or mfield in drbol_areas

            if credit > 0 and (is_general_type or is_general_field):
                general_credit += credit

        return Response({"general_credit": general_credit}, status=200)


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
# ✅ 8) 전체 필수 미이수 (major/general)
# ---------------------------
class RequiredMissingView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=404)
        transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
        if not transcript or not (getattr(transcript, "parsed_data", None) or getattr(transcript, "parsed", None)):
            return Response({"error": "성적표 데이터가 없습니다."}, status=404)
        requirement = GraduationRequirement.objects.filter(major=user.major).first()
        if not requirement:
            return Response({"error": "졸업 요건 데이터가 없습니다."}, status=500)

        courses = get_valid_courses(transcript)
        completed_by_code = { norm_code(c.get("code")) for c in courses if (c.get("code") or "").strip() }
        completed_by_name = { _norm(c.get("name")) for c in courses if c.get("name") }

        def is_completed(item: dict) -> bool:
            code = norm_code(item.get("code"))
            if code:
                return code in completed_by_code
            return _norm(item.get("name")) in completed_by_name

        major_missing = [
            {"code": i.get("code","") or "", "name": i.get("name","") or "", "semester": (i.get("semester") or "기타")}
            for i in (requirement.major_must_courses or [])
            if not is_completed(i)
        ]

        # 교양필수: 같은 이름의 여러 코드가 있을 수 있으므로 여기선 코드 단위로만 미이수 표기
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
# ✅ 9) 미이수 드볼 영역
# ---------------------------
class DrbolMissingView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=404)
        transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
        if not transcript or not (getattr(transcript, "parsed_data", None) or getattr(transcript, "parsed", None)):
            return Response({"error": "성적표 데이터가 없습니다."}, status=404)
        requirement = GraduationRequirement.objects.filter(major=user.major).first()
        if not requirement:
            return Response({"error": "졸업 요건 데이터가 없습니다."}, status=500)

        # 기준들
        areas = [a.strip() for a in (requirement.drbol_areas or "").split(",") if a.strip()]
        required_areas_count = min(6, len(areas))          # 규칙: 7개 중 6개 영역 커버
        required_credit_total = requirement.drbol_required # 보통 18

        # 수강 현황 집계
        courses = get_valid_courses(transcript)
        area_course_count = {a: 0 for a in areas}
        area_credit_sum   = {a: 0 for a in areas}
        for c in courses:
            credit = int(c.get("credit", 0) or 0)
            mf = (c.get("major_field") or "").strip()
            if mf in area_course_count:
                area_course_count[mf] += 1
                area_credit_sum[mf]   += credit

        covered_areas = [a for a in areas if area_course_count[a] >= 1]
        missing_areas = [a for a in areas if area_course_count[a] == 0]

        # 영역별 상세 rows (프런트 시각화 용)
        rows = [
            {
                "area": a,
                "covered": area_course_count[a] >= 1,
                "courses_count": area_course_count[a],
                "completed_credit": int(area_credit_sum[a]),
            }
            for a in areas
        ]

        # 총 드볼 학점: 영역 합
        drbol_credit_total = int(sum(area_credit_sum.values()))

        # 커버리지/학점 충족 판단
        coverage_ok = len(covered_areas) >= required_areas_count

        # 17학점 예외: 총 17학점이고, '커버된 영역' 중 적어도 하나의 합계가 2학점인 경우
        has_two_credit_area = any(area_credit_sum[a] == 2 for a in covered_areas)
        credit_ok = (drbol_credit_total >= required_credit_total) or (
            drbol_credit_total == 17 and has_two_credit_area
        )

        # 남은 커버 수/학점(예외 충족 시 학점 잔여 0으로 표기)
        areas_remaining = max(0, required_areas_count - len(covered_areas))
        credit_remaining = 0 if (drbol_credit_total == 17 and has_two_credit_area) \
            else max(0, required_credit_total - drbol_credit_total)

        return Response({
            "areas": rows,
            "areas_required": required_areas_count,
            "areas_covered": len(covered_areas),
            "areas_remaining": areas_remaining,
            "missing_areas": missing_areas,

            "total_credit_completed": drbol_credit_total,
            "total_credit_required": required_credit_total,
            "credit_remaining": credit_remaining,

            "coverage_ok": coverage_ok,
            "credit_ok": credit_ok,
            "status": (coverage_ok and credit_ok)
        }, status=status.HTTP_200_OK)


# ---------------------------
# ✅ 10) 필수 과목 로드맵
# ---------------------------
class RequiredRoadmapView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=404)
        transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
        if not transcript or not (getattr(transcript, "parsed_data", None) or getattr(transcript, "parsed", None)):
            return Response({"error": "성적표 데이터가 없습니다."}, status=404)
        requirement = GraduationRequirement.objects.filter(major=user.major).first()
        if not requirement:
            return Response({"error": "졸업 요건 데이터가 없습니다."}, status=500)

        courses = get_valid_courses(transcript)
        # 완료 맵: code -> taken_semester
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
