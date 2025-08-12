from rest_framework import generics, permissions, status
from rest_framework.response import Response
from transcripts.models import Transcript
from users.models import User
from .models import GraduationRequirement
from .serializers import GraduationStatusSerializer

# ---------------------------
# 유틸/공통 (code 기반)
# ---------------------------
import re
import unicodedata
from typing import Any, Dict, List

ROMAN = {"Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3", "Ⅳ": "4", "Ⅴ": "5", "Ⅵ": "6", "Ⅶ": "7", "Ⅷ": "8", "Ⅸ": "9"}

def _norm(s: str | None) -> str:
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

def get_courses_from_parsed_data(parsed) -> List[Dict[str, Any]]:
    """parsed_data 안전 추출"""
    if not parsed:
        return []
    if isinstance(parsed, dict):
        return parsed.get("courses", []) or []
    if isinstance(parsed, list):
        return parsed
    return []

def get_valid_courses(transcript) -> List[Dict[str, Any]]:
    """F 및 재수강 제외 (최근 통과 기록만) — parsed_data만 사용"""
    all_courses = get_courses_from_parsed_data(getattr(transcript, "parsed_data", None))
    return [
        c for c in all_courses
        if c and (str(c.get("grade", "")).upper() != "F") and (not c.get("retake", False))
    ]

def _add_code_credit_from_list(store: dict, items: list[dict] | None):
    if not items:
        return
    for it in items:
        code = norm_code(it.get("code"))
        credit = int(it.get("credit") or 0)
        if code and credit and code not in store:
            store[code] = credit

def build_code_credit_map(req: GraduationRequirement) -> dict[str, int]:
    """
    졸업요건 내 모든 과목을 훑어 code -> credit 매핑 생성.
    (파싱 데이터에 credit이 없어도 합산 가능)
    """
    m: dict[str, int] = {}
    _add_code_credit_from_list(m, req.major_must_courses)
    _add_code_credit_from_list(m, req.major_selective_courses)
    _add_code_credit_from_list(m, req.general_must_courses)
    _add_code_credit_from_list(m, req.general_selective_courses)
    _add_code_credit_from_list(m, req.special_general_courses)
    _add_code_credit_from_list(m, req.sw_courses)
    _add_code_credit_from_list(m, req.msc_courses)
    dr = req.drbol_courses or {}
    if isinstance(dr, dict):
        for _area, lst in dr.items():
            _add_code_credit_from_list(m, lst)
    return m

def codes_set(items: list[dict] | None) -> set[str]:
    return {norm_code(i.get("code")) for i in (items or []) if i.get("code")}

def build_code_sets(req: GraduationRequirement):
    """요건에서 분류별 코드셋/맵 생성"""
    major_must = codes_set(req.major_must_courses)
    major_sel  = codes_set(req.major_selective_courses)
    gen_must   = codes_set(req.general_must_courses)
    gen_sel    = codes_set(req.general_selective_courses)
    spec_gen   = codes_set(req.special_general_courses)
    sw_codes   = codes_set(req.sw_courses)
    msc_codes  = codes_set(req.msc_courses)

    # 드볼: 영역별 코드셋 + 전체 코드셋
    area_code_map: dict[str, set[str]] = {}
    dr_all = set()
    dr = req.drbol_courses or {}
    if isinstance(dr, dict):
        for area, lst in dr.items():
            s = codes_set(lst)
            area_code_map[area] = s
            dr_all |= s

    return {
        "major_must": major_must,
        "major_sel": major_sel,
        "gen_must": gen_must,
        "gen_sel": gen_sel,
        "spec_gen": spec_gen,
        "sw": sw_codes,
        "msc": msc_codes,
        "dr_area": area_code_map,
        "dr_all": dr_all,
    }

def credit_from_map_or_course(course: dict, code_credit_map: dict[str, int]) -> int:
    """과목 dict에 credit이 없으면 학수번호 매핑으로 보정"""
    v = course.get("credit")
    if v not in (None, "", 0):
        try:
            return int(v)
        except Exception:
            pass
    return code_credit_map.get(norm_code(course.get("code")), 0)

def sum_for_codes(courses: list[dict], target_codes: set[str], code_credit_map: dict[str, int]) -> int:
    return sum(
        credit_from_map_or_course(c, code_credit_map)
        for c in courses
        if norm_code(c.get("code")) in target_codes
    )

def distribute(total: int, n: int) -> List[int]:
    """총합을 n개로 고르게 분배 (옵션)"""
    if n <= 0:
        return []
    base = total // n
    rem = total % n
    arr = [base] * n
    for i in range(rem):
        arr[i] += 1
    return arr


# ---------------------------
# 핵심 분석 함수 (전부 code 기반)
# ---------------------------
def analyze_graduation(user_id: int):
    # 1) 유저
    user = User.objects.filter(id=user_id).first()
    if not user:
        return {"error": "사용자를 찾을 수 없습니다.", "status": 404}

    # 2) 성적표 (parsed_data만 사용)
    transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
    if not transcript or not transcript.parsed_data:
        return {"error": "성적표 데이터가 없습니다.", "status": 404}

    courses = get_valid_courses(transcript)

    # 3) 졸업요건 (전공으로 매칭)
    requirement = GraduationRequirement.objects.filter(major=user.major).first()
    if not requirement:
        return {"error": "졸업 요건 데이터가 없습니다.", "status": 500}

    # 4) 매핑/코드셋 준비
    code_credit_map = build_code_credit_map(requirement)
    S = build_code_sets(requirement)
    taken_codes = {norm_code(c.get("code")) for c in courses if c.get("code")}

    # 5) 학점 합산 — code 기반
    total_credit = sum(credit_from_map_or_course(c, code_credit_map) for c in courses)

    major_credit   = sum_for_codes(courses, S["major_must"] | S["major_sel"], code_credit_map)
    # 교양 총합 = 교양필수 + 교양선택 + 특성화교양 + 드볼
    general_credit = sum_for_codes(courses, S["gen_must"] | S["gen_sel"] | S["spec_gen"] | S["dr_all"], code_credit_map)
    drbol_credit   = sum_for_codes(courses, S["dr_all"], code_credit_map)
    sw_credit      = sum_for_codes(courses, S["sw"], code_credit_map)
    msc_credit     = sum_for_codes(courses, S["msc"], code_credit_map)
    special_general_credit = sum_for_codes(courses, S["spec_gen"], code_credit_map)

    # 6) 전공필수 미이수 (학기별 dict) — code 기준
    must_list: list[dict] = requirement.major_must_courses or []
    missing_by_semester: dict[str, list[dict]] = {}
    for item in must_list:
        code = norm_code(item.get("code"))
        if not code or code in taken_codes:
            continue
        sem = item.get("semester") or "기타"
        missing_by_semester.setdefault(sem, []).append({
            "code": item.get("code", "") or "",
            "name": item.get("name", "") or ""
        })

    # 7) 드볼 커버리지/학점 — code 기준 (7개 중 6개 커버 + 18학점; 17학점 예외)
    drbol_areas = list(S["dr_area"].keys())
    required_areas_count = min(6, len(drbol_areas))

    area_course_count = {a: 0 for a in drbol_areas}
    area_credits      = {a: 0 for a in drbol_areas}

    for c in courses:
        code = norm_code(c.get("code"))
        cred = credit_from_map_or_course(c, code_credit_map)
        for area in drbol_areas:
            if code in S["dr_area"][area]:
                area_course_count[area] += 1
                area_credits[area] += cred

    covered_areas = [a for a in drbol_areas if area_course_count[a] >= 1]
    covered_count = len(covered_areas)
    missing_drbol_areas = [a for a in drbol_areas if area_course_count[a] == 0]

    total_dvbol_credit = sum(area_credits.values())
    has_two_credit_area = any(area_credits[a] == 2 for a in covered_areas)
    coverage_ok = covered_count >= required_areas_count
    credit_ok   = (total_dvbol_credit >= requirement.drbol_required) or (
        total_dvbol_credit == 17 and has_two_credit_area
    )

    # 8) 상태 판정
    status_flag = "complete"
    messages = []
    if total_credit < requirement.total_required:
        status_flag = "pending"; messages.append(f"총 학점 {requirement.total_required - total_credit}학점 부족")
    if major_credit < requirement.major_required:
        status_flag = "pending"; messages.append(f"전공 {requirement.major_required - major_credit}학점 부족")
    if general_credit < requirement.general_required:
        status_flag = "pending"; messages.append(f"교양필수 {requirement.general_required - general_credit}학점 부족")

    # 드볼: 총 학점 + 커버리지 동시 충족 필요
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

        "drbol_completed": total_dvbol_credit,
        "drbol_required": requirement.drbol_required,

        "sw_completed": sw_credit,
        "sw_required": requirement.sw_required,

        "msc_completed": msc_credit,
        "msc_required": requirement.msc_required,

        "special_general_completed": special_general_credit,
        "special_general_required": requirement.special_general_required,

        "missing_major_courses": missing_by_semester,
        "missing_drbol_areas": missing_drbol_areas,

        "graduation_status": status_flag,
        "message": message,
    }
    return {"data": data, "status": 200}


# ---------------------------
# 1) 교양 필수 이수 여부 (실제 수강한 것만 리턴, 그룹 OR)
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
        if not transcript or not transcript.parsed_data:
            return Response({"error": "성적표 데이터가 없습니다."}, status=404)

        courses = get_valid_courses(transcript)
        taken_codes = {norm_code(c.get("code")) for c in courses if c.get("code")}

        # '전공기초영어(1)/(2)' 같은 대체 코드는 그룹 OR (괄호 숫자 제거)
        def group_key(name: str) -> str:
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

        # 각 그룹에서 '실제로 들은 코드'만 수집
        completed_items = []
        missing_groups = []
        for base, codes in groups.items():
            hit = codes & taken_codes
            if hit:
                for code in sorted(hit):
                    completed_items.append({"code": code, "name": name_by_code.get(code, base)})
            else:
                missing_groups.append(base)

        is_completed_all = (len(missing_groups) == 0) if groups else False

        return Response({
            "필수교양": completed_items,   # 실제 들은 필수교양만 노출
            "이수여부": is_completed_all
        }, status=status.HTTP_200_OK)


# ---------------------------
# 2) 전공 필수/선택 이수 여부 (code 교집합)
# ---------------------------
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
        if not transcript or not transcript.parsed_data:
            return Response({"error": "성적표 데이터가 없습니다."}, status=404)

        courses = get_valid_courses(transcript)
        taken_codes = {norm_code(c.get("code")) for c in courses if c.get("code")}

        def completed_from(require_list):
            rows = []
            for it in (require_list or []):
                code = norm_code(it.get("code"))
                if code and code in taken_codes:
                    rows.append({"code": code, "name": it.get("name", "")})
            return rows

        return Response({
            "전공필수": completed_from(req.major_must_courses),
            "전공선택": completed_from(req.major_selective_courses),
        }, status=status.HTTP_200_OK)


# ---------------------------
# 3) 총 이수 학점
# ---------------------------
class TotalCreditView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])
        return Response({"total_credit": result["data"]["total_completed"]})


# ---------------------------
# 4) 교양 학점 (분석값 그대로 사용)
# ---------------------------
class GeneralCreditView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])
        return Response({"general_credit": result["data"]["general_completed"]}, status=200)


# ---------------------------
# 5) 전공 학점 (분석값 그대로 사용)
# ---------------------------
class MajorCreditView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])
        return Response({"major_credit": result["data"]["major_completed"]})


# ---------------------------
# 6) 이수율 (전공/교양)
# ---------------------------
class StatisticsCreditView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        # major_rate는 기존처럼 학점 기반 사용
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])
        d = result["data"]
        major_rate = d["major_completed"] / d["major_required"] if d["major_required"] else 0.0

        # ✅ general_rate는 '교양 필수 그룹 충족률'로 계산
        user = User.objects.filter(id=user_id).first()
        req = GraduationRequirement.objects.filter(major=user.major).first() if user else None
        transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
        if not req or not transcript or not transcript.parsed_data:
            return Response({"general_rate": 0.0, "major_rate": major_rate}, status=200)

        courses = get_valid_courses(transcript)
        taken_codes = { norm_code(c.get("code")) for c in courses if c.get("code") }

        # (1)/(2) 같은 대체코드는 같은 그룹으로 묶기
        import re
        def group_key(name: str) -> str:
            if not name:
                return ""
            m = re.match(r"^(.*?)(?:\(\s*\d+\s*\))$", name.strip())
            return (m.group(1) if m else name.strip())

        # 이름 그룹 -> 코드셋
        groups: dict[str, set[str]] = {}
        for i in (req.general_must_courses or []):
            name = group_key(i.get("name", ""))
            code = norm_code(i.get("code"))
            if not name or not code:
                continue
            groups.setdefault(name, set()).add(code)

        total_groups = len(groups)
        completed_groups = sum(1 for codes in groups.values() if (codes & taken_codes))
        general_rate = (completed_groups / total_groups) if total_groups else 0.0

        return Response({"general_rate": general_rate, "major_rate": major_rate})


# ---------------------------
# 7) 졸업 요건 종합 상태
# ---------------------------
class StatusCreditView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = GraduationStatusSerializer

    def get(self, request, user_id):
        result = analyze_graduation(user_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])
        return Response(result["data"], status=status.HTTP_200_OK)


# ---------------------------
# 8) 전체 학기 필수 미이수 (major/general)
#    - general: 같은 이름(그룹) 중 하나라도 이수했으면 그 그룹은 제외
# ---------------------------
class RequiredMissingView(generics.RetrieveAPIView):
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
        taken_codes = {norm_code(c.get("code")) for c in courses if c.get("code")}

        # 전공필수: 개별 code 기준
        major_missing = []
        for i in (requirement.major_must_courses or []):
            code = norm_code(i.get("code"))
            if code and code not in taken_codes:
                major_missing.append({
                    "code": i.get("code", "") or "",
                    "name": i.get("name", "") or "",
                    "semester": (i.get("semester") or "기타")
                })

        # 교양필수: 같은 이름 그룹 OR — 그룹 중 하나라도 들었으면 그 그룹 전체 제외
        def group_key(name: str) -> str:
            if not name:
                return ""
            m = re.match(r"^(.*?)(?:\(\s*\d+\s*\))$", name.strip())
            return (m.group(1) if m else name.strip())

        groups: dict[str, list[dict]] = {}
        for i in (requirement.general_must_courses or []):
            name = group_key(i.get("name", ""))
            code = norm_code(i.get("code"))
            if not name or not code:
                continue
            groups.setdefault(name, []).append(i)

        general_missing = []
        for base, lst in groups.items():
            codes = {norm_code(x.get("code")) for x in lst}
            if codes & taken_codes:
                # 그룹 중 하나라도 들었으면 이 그룹은 미이수에서 제외
                continue
            # 아무 것도 안 들었다면 그룹의 모든 항목(또는 대표 1개)을 미이수로 표기
            # 여기서는 '모두' 표기 (필요시 lst[:1]로 대표만 표기 가능)
            for it in lst:
                general_missing.append({
                    "code": it.get("code", "") or "",
                    "name": it.get("name", "") or ""
                })

        return Response({
            "major_required_missing": major_missing,
            "general_required_missing": general_missing
        }, status=status.HTTP_200_OK)


# ---------------------------
# 9) 미이수 드볼 영역 (커버리지+학점)
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

        # 코드셋/매핑
        code_credit_map = build_code_credit_map(requirement)
        S = build_code_sets(requirement)

        areas = list(S["dr_area"].keys())
        required_areas_count = min(6, len(areas))
        courses = get_valid_courses(transcript)

        area_course_count = {a: 0 for a in areas}
        area_credit_sum   = {a: 0 for a in areas}

        for c in courses:
            code = norm_code(c.get("code"))
            cred = credit_from_map_or_course(c, code_credit_map)
            for a in areas:
                if code in S["dr_area"][a]:
                    area_course_count[a] += 1
                    area_credit_sum[a]   += cred

        covered_areas = [a for a in areas if area_course_count[a] >= 1]
        missing_areas = [a for a in areas if area_course_count[a] == 0]

        rows = [
            {
                "area": a,
                "covered": area_course_count[a] >= 1,
                "courses_count": area_course_count[a],
                "completed_credit": int(area_credit_sum[a]),
            }
            for a in areas
        ]

        drbol_credit_total = int(sum(area_credit_sum.values()))
        has_two_credit_area = any(area_credit_sum[a] == 2 for a in covered_areas)
        coverage_ok = len(covered_areas) >= required_areas_count
        credit_ok = (drbol_credit_total >= requirement.drbol_required) or (
            drbol_credit_total == 17 and has_two_credit_area
        )

        areas_remaining = max(0, required_areas_count - len(covered_areas))
        credit_remaining = 0 if (drbol_credit_total == 17 and has_two_credit_area) \
            else max(0, requirement.drbol_required - drbol_credit_total)

        return Response({
            "areas": rows,
            "areas_required": required_areas_count,
            "areas_covered": len(covered_areas),
            "areas_remaining": areas_remaining,
            "missing_areas": missing_areas,

            "total_credit_completed": drbol_credit_total,
            "total_credit_required": requirement.drbol_required,
            "credit_remaining": credit_remaining,

            "coverage_ok": coverage_ok,
            "credit_ok": credit_ok,
            "status": (coverage_ok and credit_ok)
        }, status=status.HTTP_200_OK)


# ---------------------------
# 10) 필수 과목 로드맵 (code 기준)
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
        complete_map: dict[str, str] = {}
        for c in courses:
            key = norm_code(c.get("code"))
            if key and key not in complete_map:
                complete_map[key] = c.get("semester") or None

        def build(items: list[dict]) -> list[dict]:
            rows = []
            for it in (items or []):
                key = norm_code(it.get("code"))
                taken = complete_map.get(key)
                rows.append({
                    "code": it.get("code", "") or "",
                    "name": it.get("name", "") or "",
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
