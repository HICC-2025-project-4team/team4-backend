import re
import unicodedata
from collections import defaultdict, OrderedDict
from typing import Any, Dict, List, Set

from transcripts.models import Transcript
from users.models import User
from .models import GraduationRequirement

# --- 유틸리티 함수 ---
def _norm_code(x) -> str:
    s = re.sub(r"\D", "", str(x or ""))
    return s.zfill(6) if s else ""

def _group_key_general(name: str) -> str:
    if not name: return ""
    m = re.match(r"^(.*?)(?:\(\s*\d+\s*\))?$", name.strip())
    return (m.group(1) if m else name.strip())

def _parse_semester(term_str: str) -> str:
    """'학년도'를 정확히 제외하고 '1학년 2학기' -> '1-2'로 파싱합니다."""
    if not term_str: return "기타"
    # '학년' 뒤에 '도'가 오지 않는 경우에만 매칭 (Negative Lookahead)
    year_match = re.search(r'(\d)\s*학년(?!도)', term_str)
    semester_match = re.search(r'(\d)\s*학기', term_str)
    if year_match and semester_match:
        return f"{year_match.group(1)}-{semester_match.group(1)}"
    return "기타"

# --- 핵심 서비스 클래스 ---
class GraduationAnalysisService:
    def __init__(self, user_id: int):
        self.user = User.objects.filter(id=user_id).first()
        self.transcript = Transcript.objects.filter(user_id=user_id).order_by("-created_at").first()
        self.requirement = GraduationRequirement.objects.filter(major=self.user.major).first() if self.user else None
        
        self.is_ready = all([self.user, self.transcript, self.transcript.parsed_data, self.requirement])
        if not self.is_ready: return

        # 1. 기초 데이터 준비
        self._prepare_base_data()
        
        # 2. 모든 분석을 순차적으로 실행하고 결과를 self.analysis_result에 저장
        self._run_full_analysis()

    def _prepare_base_data(self):
        """[핵심] OCR 데이터에 semester, name, credit 필드가 없어도 즉석에서 파싱하고 채웁니다."""
        req = self.requirement
        
        self.req_course_db = {}
        def _add_to_db(items, course_type):
            for item in (items or []):
                code = _norm_code(item.get("code"))
                if code and code not in self.req_course_db: self.req_course_db[code] = {**item, 'type': course_type}
        
        _add_to_db(req.major_must_courses, "전공필수"); _add_to_db(req.major_selective_courses, "전공선택")
        _add_to_db(req.general_must_courses, "교양필수"); _add_to_db(req.general_selective_courses, "교양선택")
        _add_to_db(req.special_general_courses, "특성화교양"); _add_to_db(req.sw_courses, "SW/데이터"); _add_to_db(req.msc_courses, "MSC")
        if isinstance(req.drbol_courses, dict):
            for area, lst in req.drbol_courses.items(): _add_to_db(lst, f"드볼({area})")

        parsed = self.transcript.parsed_data
        courses_data = parsed.get("courses", parsed) if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
        
        self.valid_courses = []
        for course in courses_data:
            if not course or str(course.get("grade", "")).upper() == "F" or course.get("retake", False): continue
            code = _norm_code(course.get("code"))
            db_info = self.req_course_db.get(code, {})
            semester = course.get("semester") or _parse_semester(course.get("term", ""))
            self.valid_courses.append({
                "name": course.get("name") or db_info.get("name", "미등록과목"), "code": course.get("code", ""),
                "credit": int(course.get("credit") or db_info.get("credit", 0)),
                "type": db_info.get("type", "기타"), "grade": course.get("grade", ""), "semester": semester,
            })
            
        self.taken_codes = {_norm_code(c.get("code")) for c in self.valid_courses}
        
        self.req_code_sets = {}
        def _get_codes(items): return {_norm_code(i.get("code")) for i in (items or []) if i.get("code")}
        self.req_code_sets['major_must'] = _get_codes(req.major_must_courses); self.req_code_sets['major_sel'] = _get_codes(req.major_selective_courses)
        self.req_code_sets['gen_must'] = _get_codes(req.general_must_courses); self.req_code_sets['gen_sel'] = _get_codes(req.general_selective_courses)
        self.req_code_sets['spec_gen'] = _get_codes(req.special_general_courses); self.req_code_sets['sw'] = _get_codes(req.sw_courses)
        self.req_code_sets['msc'] = _get_codes(req.msc_courses)
        dr_area_map, dr_all = {}, set()
        if isinstance(req.drbol_courses, dict):
            for area, lst in req.drbol_courses.items():
                s = _get_codes(lst); dr_area_map[area] = s; dr_all |= s
        self.req_code_sets['dr_area'] = dr_area_map; self.req_code_sets['dr_all'] = dr_all

    def _credit_from_course(self, course: dict) -> int: return course.get("credit", 0)
    def _sum_credit_for_codes(self, target_codes: set) -> int: return sum(self._credit_from_course(c) for c in self.valid_courses if _norm_code(c.get("code")) in target_codes)

    def _run_full_analysis(self):
        req, S = self.requirement, self.req_code_sets
        drbol_status = self._calculate_drbol_status() # 먼저 계산
        
        result = {
            "major_completed": self._sum_credit_for_codes(S['major_must'] | S['major_sel']),
            "general_completed": self._sum_credit_for_codes(S['gen_must']),
            "drbol_completed": self._sum_credit_for_codes(S['dr_all']),
            "sw_completed": self._sum_credit_for_codes(S['sw']),
            "msc_completed": self._sum_credit_for_codes(S['msc']),
            "special_general_completed": self._sum_credit_for_codes(S['spec_gen']),
            "total_completed": sum(self._credit_from_course(c) for c in self.valid_courses),
        }

        missing_major = defaultdict(list)
        for item in (req.major_must_courses or []):
            code = _norm_code(item.get("code"))
            if code and code not in self.taken_codes:
                missing_major[item.get("semester", "기타")].append({"code": item.get("code"), "name": item.get("name")})
        result["missing_major_courses"] = dict(missing_major)
        result["missing_drbol_areas"] = drbol_status["missing_areas"]
        
        messages = []
        if result["total_completed"] < req.total_required: messages.append(f"총 학점 {req.total_required - result['total_completed']}학점 부족")
        if result["major_completed"] < req.major_required: messages.append(f"전공 {req.major_required - result['major_completed']}학점 부족")
        if result["general_completed"] < req.general_required: messages.append(f"교양필수 {req.general_required - result['general_completed']}학점 부족")
        if result["drbol_completed"] < req.drbol_required: messages.append(f"드볼 학점 {req.drbol_required - result['drbol_completed']}학점 부족")
        if result["sw_completed"] < req.sw_required: messages.append(f"SW/데이터활용 {req.sw_required - result['sw_completed']}학점 부족")
        if result["msc_completed"] < req.msc_required: messages.append(f"MSC {req.msc_required - result['msc_completed']}학점 부족")
        if result["special_general_completed"] < req.special_general_required: messages.append(f"특성화교양 {req.special_general_required - result['special_general_completed']}학점 부족")
        if any(missing_major.values()): messages.append("전공 필수 미이수 존재")
        
        result.update({
            "total_required": req.total_required, "major_required": req.major_required,
            "general_required": req.general_required, "drbol_required": req.drbol_required,
            "sw_required": req.sw_required, "msc_required": req.msc_required,
            "special_general_required": req.special_general_required,
            "graduation_status": "pending" if messages else "complete",
            "message": " / ".join(messages) if messages else "졸업 요건 충족",
        })
        self.analysis_result = result

    def _calculate_drbol_status(self):
        S, req = self.req_code_sets, self.requirement
        areas = list(S["dr_area"].keys())
        req_areas_count = min(6, len(areas))
        
        area_stats = {a: {'count': 0, 'credit': 0} for a in areas}
        for c in self.valid_courses:
            code = _norm_code(c.get("code"))
            for area in areas:
                if code in S['dr_area'][area]:
                    area_stats[area]['count'] += 1; area_stats[area]['credit'] += self._credit_from_course(c)

        covered_areas = [a for a, stat in area_stats.items() if stat['count'] > 0]
        
        return {
            "areas": [{"area": a, "covered": s['count']>0, "courses_count": s['count'], "completed_credit": s['credit']} for a, s in area_stats.items()],
            "areas_required": req_areas_count, "areas_covered": len(covered_areas),
            "missing_areas": [a for a, s in area_stats.items() if s['count'] == 0],
            "total_credit_completed": sum(s['credit'] for s in area_stats.values()),
            "total_credit_required": req.drbol_required,
        }

    # --- Public Methods for Views ---
    def get_general_courses_status(self):
        groups = defaultdict(set); name_map = {}
        for item in (self.requirement.general_must_courses or []):
            code, name = _norm_code(item.get('code')), item.get('name','')
            if not (code and name): continue
            groups[_group_key_general(name)].add(code)
            name_map[code] = name
        
        completed_items = []; missing_groups = []
        for key, codes in groups.items():
            hit_codes = codes & self.taken_codes
            if not hit_codes:
                missing_groups.append(key)
            else:
                for code in hit_codes: completed_items.append({"code": code, "name": name_map[code]})
        
        return {"필수교양": completed_items, "이수여부": not bool(missing_groups)}

    def get_major_courses_status(self):
        def completed_from(req_list):
            return [{"code": item.get("code"), "name": item.get("name")} for item in (req_list or []) if _norm_code(item.get("code")) in self.taken_codes]
        return {"전공필수": completed_from(self.requirement.major_must_courses), "전공선택": completed_from(self.requirement.major_selective_courses)}

    def get_credit_statistics(self):
        res = self.analysis_result
        major_rate = res["major_completed"] / res["major_required"] if res["major_required"] else 0
        groups = defaultdict(set)
        for item in (self.requirement.general_must_courses or []):
             if item.get('code') and item.get('name'):
                groups[_group_key_general(item['name'])].add(_norm_code(item['code']))
        completed_groups = sum(1 for codes in groups.values() if codes & self.taken_codes)
        general_rate = completed_groups / len(groups) if groups else 0
        return {"general_rate": general_rate, "major_rate": major_rate}
        
    def get_drbol_status(self):
        return self._calculate_drbol_status()

    def get_required_roadmap(self):
        complete_map = { _norm_code(c.get("code")): c.get("semester") for c in self.valid_courses if c.get("code") }
        major_roadmap = []
        for it in (self.requirement.major_must_courses or []):
            key = _norm_code(it.get("code"))
            major_roadmap.append({
                "code": it.get("code", ""), "name": it.get("name", ""),
                "planned_semester": it.get("semester"), "completed": key in complete_map,
                "taken_semester": complete_map.get(key)
            })
        general_roadmap = []
        groups = OrderedDict()
        for it in (self.requirement.general_must_courses or []):
            if it.get('name') and it.get('code'):
                groups.setdefault(_group_key_general(it['name']), []).append(it)
        
        for gname, items in groups.items():
            hit_code = next((_norm_code(x.get("code")) for x in items if _norm_code(x.get("code")) in complete_map), None)
            rep = next((x for x in items if _norm_code(x.get("code")) == hit_code), items[0])
            general_roadmap.append({
                "code": rep.get("code", ""), "name": gname,
                "planned_semester": rep.get("semester"), "completed": bool(hit_code),
                "taken_semester": complete_map.get(hit_code)
            })
        return {"major_required_roadmap": major_roadmap, "general_required_roadmap": general_roadmap}