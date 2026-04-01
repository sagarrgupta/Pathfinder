from app.agents.course_planner import _heuristic_course_payload
from app.agents.evaluator import _validate_decision_payload
from app.agents.fact_extractor import _heuristic_records
from app.agents.eligibility_reasoner import _heuristic_eligibility_payload
from app.agents.orchestrator import _ensure_quality_course_plan
from app.agents.program_advisor import _heuristic_program_payload
from app.agents.career_matcher import _heuristic_career_payload
from app.agents.web_researcher import _preferred_domains, _result_score
from app.core.quality import (
    analyze_query_focus,
    build_task_graph,
    build_session_summary,
    build_source_policy,
    classify_web_source,
    compact_session_state,
    extract_course_entries,
    group_evidence_records,
    infer_evidence_tiers,
    infer_student_workflow,
    infer_target_entity,
    summarize_trace,
)


def test_session_summary_prefers_latest_student_state():
    summary = build_session_summary(
        {"personal": {"university": "California State University - Sacramento", "program": "Computer Science"}},
        [("human", "I am in my first semester and want to become an AI engineer")],
        "Which courses can I take next semester?",
    )

    assert summary["institution"]["value"] == "California State University - Sacramento"
    assert summary["standing"]["value"] == "first semester"
    assert "AI engineer" in summary["goals"]["value"]


def test_session_summary_extracts_generic_institution_program_and_goal():
    summary = build_session_summary(
        {"personal": {}},
        [("human", "I study at Boston University and I am majoring in Data Science.")],
        "I want to become a product manager.",
    )

    assert summary["institution"]["value"] == "Boston University"
    assert summary["program"]["value"] == "Data Science"
    assert "product manager" in [goal.lower() for goal in summary["goals"]["value"]]


def test_target_entity_and_source_policy_are_dynamic_for_program_queries():
    summary = build_session_summary(
        {"personal": {"university": "Boston University", "program": "Data Science MS"}},
        [],
        "What are the admission requirements for my program?",
    )
    focus = analyze_query_focus("What are the admission requirements for my program?")
    entity = infer_target_entity({"personal": {"university": "Boston University", "program": "Data Science MS"}}, summary, "What are the admission requirements for my program?", focus)
    policy = build_source_policy(focus, entity, "program_understanding", ["bu.edu"])

    assert entity["kind"] == "program"
    assert entity["program"] == "Data Science MS"
    assert "degree_page" in policy["primary_source_types"]
    assert "admissions_page" in policy["primary_source_types"]
    assert policy["prefer_pdfs"] is True
    assert policy["strict_primary_only"] is True


def test_target_entity_and_source_policy_shift_for_job_queries():
    focus = analyze_query_focus("What jobs fit me based on my profile?")
    entity = infer_target_entity({}, {}, "What jobs fit me based on my profile?", focus)
    policy = build_source_policy(focus, entity, "career_alignment", [])

    assert entity["kind"] == "job_role"
    assert policy["primary_source_types"] == ["job_page", "profile_doc"]
    assert policy["strict_primary_only"] is False


def test_build_task_graph_for_academic_planning_is_dependency_aware():
    focus = analyze_query_focus("Which courses can I enroll in next semester?")
    graph = build_task_graph(
        "Which courses can I enroll in next semester?",
        "academic_planning",
        focus,
        {"kind": "program", "program": "Computer Science", "level": "graduate"},
    )

    ids = [task["id"] for task in graph]
    assert ids[0] == "load_student_state"
    assert "load_conversation_state" in ids
    assert "determine_decision_goal" in ids
    assert "retrieve_primary_sources" in ids
    assert "retrieve_live_schedule" in ids
    assert "extract_requirements" in ids
    assert "extract_courses" in ids
    assert "compare_to_student_state" in ids
    assert "rank_options" in ids
    assert graph[-1]["id"] == "render_final_answer"


def test_workflow_inference_is_general_for_student_questions():
    assert infer_student_workflow(
        "Can I take this course next semester?",
        analyze_query_focus("Can I take this course next semester?"),
        [],
        {"kind": "program", "program": "Computer Science", "level": "graduate"},
    ) == "eligibility_check"

    assert infer_student_workflow(
        "Can I finish in 2 years?",
        analyze_query_focus("Can I finish in 2 years?"),
        [],
        {"kind": "program", "program": "Computer Science", "level": "graduate"},
    ) == "academic_planning"

    assert infer_student_workflow(
        "Compare these two programs for me",
        analyze_query_focus("Compare these two programs for me"),
        [],
        {"kind": "program", "program": "Computer Science", "level": "graduate"},
    ) == "comparison_guidance"


def test_course_plan_path_prunes_extra_program_agents():
    plan = _ensure_quality_course_plan(["profile_manager", "web_researcher", "program_advisor"])
    assert plan == ["profile_manager", "web_researcher", "fact_extractor", "course_planner"]


def test_classify_web_source_distinguishes_degree_and_schedule():
    assert classify_web_source(
        "https://catalog.csus.edu/ms",
        "MS in Computer Science",
        "program requirements curriculum",
    ) == ("degree_page", "catalog")

    assert classify_web_source(
        "https://csus.edu/schedule",
        "Schedule of Classes",
        "open seats section times fall 2026",
    ) == ("schedule_page", "live_schedule")


def test_extract_course_entries_parses_code_and_title_pairs():
    entries = extract_course_entries(
        "CSC 200 Professional Writing in Computer Science\nCSC 215 Artificial Intelligence\nCSC 219 Machine Learning"
    )

    assert {"code": "CSC 200", "name": "Professional Writing in Computer Science"} in entries
    assert {"code": "CSC 215", "name": "Artificial Intelligence"} in entries


def test_fact_extractor_heuristics_preserve_mixed_sources():
    records = _heuristic_records(
        {"courses": [], "skills": [], "goals": []},
        [],
        [
            {
                "title": "MS in Computer Science",
                "url": "https://catalog.csus.edu/ms",
                "content": "Required courses include CSC 201, CSC 205, CSC 206.",
            },
            {
                "title": "Certificate in Intelligent Systems",
                "url": "https://catalog.csus.edu/certificate",
                "content": "Students may take CSC 214, CSC 215, CSC 219.",
            },
        ],
        analyze_query_focus("Which graduate courses and related specializations should I plan for?"),
        "Computer Science",
        "graduate",
    )

    source_types = {record["source_type"] for record in records}
    codes = {record["value"]["code"] for record in records if "code" in record["value"]}

    assert "degree_page" in source_types
    assert "certificate_page" in source_types
    assert "CSC 201" in codes
    assert "CSC 215" in codes


def test_fact_extractor_emits_richer_schema_fields():
    records = _heuristic_records(
        {"courses": [], "skills": [], "goals": []},
        [],
        [
            {
                "title": "Schedule of Classes",
                "url": "https://www.csus.edu/schedule",
                "content": "CSC 215 Artificial Intelligence 3 units Fall 2026 open seats section 01",
            },
            {
                "title": "Machine Learning Engineer Intern",
                "url": "https://jobs.example/ml",
                "content": "Remote position. TensorFlow experience preferred.",
            },
        ],
        analyze_query_focus("Which courses are available next semester and what jobs fit me?"),
        "Computer Science",
        "graduate",
    )

    availability = [r for r in records if r["entity_type"] == "availability"]
    roles = [r for r in records if r["entity_type"] == "job_role"]
    deadlines = [r for r in records if r["entity_type"] == "deadline"]

    assert availability
    assert availability[0]["value"]["terms"] == ["Fall 2026"]
    assert availability[0]["value"]["units"] == [3]
    assert roles
    assert roles[0]["value"]["work_mode"] == "remote"
    assert deadlines == []


def test_infer_evidence_tiers_distinguishes_official_vs_third_party():
    official = infer_evidence_tiers(
        "https://catalog.csus.edu/ms-in-computer-science",
        "degree_page",
        "Computer Science",
        "graduate",
        "MS in Computer Science",
        "Official graduate program requirements",
    )
    third_party = infer_evidence_tiers(
        "https://www.shiksha.com/ms-in-computer-science",
        "general_web",
        "Computer Science",
        "graduate",
        "MS in Computer Science Overview",
        "Third-party summary page",
    )

    assert official[0] == "primary_official"
    assert official[1] == "direct"
    assert third_party[0] == "third_party"


def test_fact_extractor_uses_course_catalog_page_for_grad_course_entries():
    records = _heuristic_records(
        {"courses": [], "skills": [], "goals": []},
        [],
        [
            {
                "title": "Computer Science (CSC) | Sacramento State Catalog",
                "url": "https://catalog.csus.edu/courses-a-z/csc/",
                "content": "CSC 200 Professional Writing in Computer Science. CSC 215 Artificial Intelligence. CSC 219 Machine Learning.",
            },
        ],
        analyze_query_focus("Which courses can I enroll in next semester?"),
        "Computer Science",
        "graduate",
        {"primary_source_types": ["schedule_page", "degree_page"], "secondary_source_types": ["general_web", "certificate_page"]},
    )

    labels = {(record["value"].get("code", ""), record["value"].get("name", "")) for record in records if record["entity_type"] == "course"}
    assert ("CSC 200", "Professional Writing in Computer Science") in labels
    assert ("CSC 215", "Artificial Intelligence") in labels


def test_group_evidence_records_buckets_typed_facts():
    grouped = group_evidence_records(
        [
            {"entity_type": "requirement", "value": {"summary": "30 units"}},
            {"entity_type": "availability", "value": {"code": "CSC 215"}},
            {"entity_type": "skill", "source_type": "job_page", "value": {"name": "TensorFlow"}},
            {"entity_type": "skill", "source_type": "profile_doc", "value": {"name": "Python"}},
        ],
        {"skills": [{"name": "Python"}]},
    )

    assert len(grouped["requirements"]) == 1
    assert len(grouped["availability"]) == 1
    assert len(grouped["missing_skills"]) == 1
    assert len(grouped["profile_skills"]) == 1


def test_fact_extractor_filters_irrelevant_department_and_undergrad_courses():
    records = _heuristic_records(
        {"courses": [], "skills": [], "goals": []},
        [],
        [
            {
                "title": "MA in Education (Curriculum and Instruction)",
                "url": "https://catalog.csus.edu/education/ma-education",
                "content": "EDBM 250 EDCI 227 EDCI 251 graduate education courses",
            },
            {
                "title": "Computer Science Courses - Class schedule",
                "url": "https://www.csus.edu/class-schedule/fall-2024/csc",
                "content": "CSC 130 CSC 131 undergraduate sections",
            },
            {
                "title": "MS in Computer Science",
                "url": "https://catalog.csus.edu/colleges/engineering-computer-science/computer-science/ms-in-computer-science/",
                "content": "Required courses include CSC 201 CSC 205 CSC 206",
            },
        ],
        analyze_query_focus("Which courses can I enroll in next semester?"),
        "Computer Science",
        "graduate",
    )

    codes = {record["value"]["code"] for record in records if "code" in record.get("value", {})}
    assert "EDBM 250" not in codes
    assert "EDCI 227" not in codes
    assert "CSC 130" not in codes
    assert "CSC 131" not in codes
    assert "CSC 201" in codes


def test_course_planner_prioritizes_core_and_goal_aligned_courses():
    summary = {
        "goals": {"value": ["AI engineer"]},
        "completed_courses": {"value": []},
        "assumptions": [],
    }
    evidence = [
        {
            "source_type": "degree_page",
            "entity_type": "course",
            "value": {"code": "CSC 206", "name": "Algorithms and Paradigms"},
            "source_url": "https://catalog.csus.edu/ms",
            "source_title": "MS in Computer Science",
            "excerpt": "Required core course CSC 206.",
            "time_scope": "catalog",
        },
        {
            "source_type": "certificate_page",
            "entity_type": "course",
            "value": {"code": "CSC 215", "name": "Artificial Intelligence"},
            "source_url": "https://catalog.csus.edu/certificate",
            "source_title": "Certificate in Intelligent Systems",
            "excerpt": "CSC 215 Artificial Intelligence.",
            "time_scope": "catalog",
        },
    ]

    payload = _heuristic_course_payload(summary, group_evidence_records(evidence, {}))
    labels = [item["label"] for item in payload["recommended_items"]]

    assert any("CSC 206" in label for label in labels)
    assert any("CSC 215" in label for label in labels)
    assert payload["decision_type"] == "course_planning"


def test_course_planner_refuses_irrelevant_undergrad_fallbacks_for_graduate_plan():
    summary = {
        "program": {"value": "Computer Science"},
        "goals": {"value": []},
        "completed_courses": {"value": []},
        "assumptions": [],
    }
    evidence = [
        {
            "source_type": "schedule_page",
            "entity_type": "availability",
            "value": {"code": "CSC 130", "name": "Data Structures"},
            "source_url": "https://www.csus.edu/class-schedule/fall-2024/csc",
            "source_title": "Computer Science Courses - Class schedule",
            "excerpt": "CSC 130 undergraduate section",
            "time_scope": "live_schedule",
        },
        {
            "source_type": "degree_page",
            "entity_type": "course",
            "value": {"code": "EDCI 227", "name": "Curriculum Theory"},
            "source_url": "https://catalog.csus.edu/education/ma-education",
            "source_title": "MA in Education (Curriculum and Instruction)",
            "excerpt": "Graduate education course",
            "time_scope": "catalog",
        },
    ]

    payload = _heuristic_course_payload(summary, group_evidence_records(evidence, {}), "Computer Science", "graduate")

    assert payload["recommended_items"] == []
    assert payload["blocked_or_uncertain_items"]


def test_validate_decision_payload_drops_unsupported_recommendations():
    payload = {
        "recommended_items": [
            {"label": "CSC 206 Algorithms", "support_codes": ["CSC 206"]},
            {"label": "CSC 999 Invented", "support_codes": ["CSC 999"]},
        ],
        "blocked_or_uncertain_items": [],
        "source_refs": [{"title": "MS in CS", "url": "https://catalog.csus.edu/ms", "entity_type": "course"}],
    }
    evidence = [
        {
            "source_url": "https://catalog.csus.edu/ms",
            "value": {"code": "CSC 206"},
        }
    ]

    validated = _validate_decision_payload(payload, evidence)

    assert len(validated["recommended_items"]) == 1
    assert validated["recommended_items"][0]["label"] == "CSC 206 Algorithms"
    assert validated["blocked_or_uncertain_items"]


def test_validate_decision_payload_drops_invented_textual_recommendation():
    payload = {
        "recommended_items": [
            {"label": "CS 601 Advanced Algorithms", "support_codes": [], "reason": "Good first semester option."},
            {"label": "MS in Computer Science requirement summary", "support_codes": [], "reason": "This is supported by the degree page."},
        ],
        "blocked_or_uncertain_items": [],
        "source_refs": [{"title": "MS in Computer Science", "url": "https://catalog.csus.edu/ms", "entity_type": "requirement"}],
    }
    evidence = [
        {
            "source_url": "https://catalog.csus.edu/ms",
            "source_title": "MS in Computer Science",
            "excerpt": "The MS requires 30 units and core courses.",
            "value": {"summary": "30-unit MS requirement"},
        }
    ]

    validated = _validate_decision_payload(payload, evidence)

    labels = [item["label"] for item in validated["recommended_items"]]
    assert "CS 601 Advanced Algorithms" not in labels
    assert "MS in Computer Science requirement summary" in labels


def test_program_advisor_builds_structured_requirement_guidance():
    summary = {
        "institution": {"value": "California State University - Sacramento"},
        "program": {"value": "Computer Science (MS)"},
        "assumptions": [],
    }
    evidence = [
        {
            "source_type": "degree_page",
            "entity_type": "requirement",
            "value": {"summary": "30-unit MS requirement"},
            "source_url": "https://catalog.csus.edu/ms",
            "source_title": "MS in Computer Science",
            "excerpt": "The MS requires 30 units and core courses.",
        },
        {
            "source_type": "admissions_page",
            "entity_type": "program_constraint",
            "value": {"summary": "Fully classified status"},
            "source_url": "https://catalog.csus.edu/admissions",
            "source_title": "Admissions",
            "excerpt": "Students with deficiencies may need to remove them.",
        },
    ]

    payload = _heuristic_program_payload(summary, group_evidence_records(evidence, {}))

    assert payload["decision_type"] == "program_guidance"
    assert payload["recommended_items"]
    assert payload["blocked_or_uncertain_items"]


def test_career_matcher_builds_structured_role_and_gap_guidance():
    summary = {
        "goals": {"value": ["AI engineer"]},
        "assumptions": [],
    }
    profile = {
        "skills": [{"name": "Python"}],
        "courses": [{"code": "CSC 206"}],
    }
    evidence = [
        {
            "source_type": "job_page",
            "entity_type": "job_role",
            "value": {"name": "Machine Learning Engineer Intern"},
            "source_url": "https://jobs.example/ml",
            "source_title": "Machine Learning Engineer Intern",
            "excerpt": "Python and ML experience preferred.",
        },
        {
            "source_type": "job_page",
            "entity_type": "skill",
            "value": {"name": "TensorFlow"},
            "source_url": "https://jobs.example/ml",
            "source_title": "Machine Learning Engineer Intern",
            "excerpt": "TensorFlow experience preferred.",
        },
    ]

    payload = _heuristic_career_payload(summary, profile, group_evidence_records(evidence, profile))

    assert payload["decision_type"] == "career_matching"
    assert payload["recommended_items"]
    assert payload["blocked_or_uncertain_items"]


def test_web_result_scoring_prefers_degree_page_for_requirements():
    focus = analyze_query_focus("What are the MS CS requirements at Sacramento State?")
    policy = build_source_policy(
        focus,
        {"kind": "program", "program": "Computer Science", "level": "graduate"},
        "program_understanding",
        ["csus.edu"],
    )
    degree_score = _result_score(
        {
            "url": "https://catalog.csus.edu/ms-in-computer-science",
            "title": "MS in Computer Science",
            "content": "program requirements curriculum 30 units",
            "score": 0.1,
        },
        "What are the MS CS requirements at Sacramento State?",
        ["csus.edu"],
        focus,
        "Computer Science",
        "graduate",
        policy,
    )
    cert_score = _result_score(
        {
            "url": "https://catalog.csus.edu/certificate-in-intelligent-systems",
            "title": "Certificate in Intelligent Systems",
            "content": "specialization certificate courses",
            "score": 0.1,
        },
        "What are the MS CS requirements at Sacramento State?",
        ["csus.edu"],
        focus,
        "Computer Science",
        "graduate",
        policy,
    )

    assert degree_score > cert_score


def test_web_result_scoring_prefers_schedule_for_live_availability():
    focus = analyze_query_focus("Which classes can I enroll in next semester?")
    policy = build_source_policy(
        focus,
        {"kind": "program", "program": "Computer Science", "level": "graduate"},
        "academic_planning",
        ["csus.edu"],
    )
    schedule_score = _result_score(
        {
            "url": "https://www.csus.edu/schedule",
            "title": "Schedule of Classes",
            "content": "open seats section Fall 2026 CSC 215",
            "score": 0.1,
        },
        "Which classes can I enroll in next semester?",
        ["csus.edu"],
        focus,
        "Computer Science",
        "graduate",
        policy,
    )
    degree_score = _result_score(
        {
            "url": "https://catalog.csus.edu/ms-in-computer-science",
            "title": "MS in Computer Science",
            "content": "curriculum requirements",
            "score": 0.1,
        },
        "Which classes can I enroll in next semester?",
        ["csus.edu"],
        focus,
        "Computer Science",
        "graduate",
        policy,
    )

    assert schedule_score > degree_score


def test_preferred_domains_are_inferred_from_generic_profile_fields():
    domains = _preferred_domains(
        {
            "personal": {
                "university_website": "https://www.bu.edu/academics",
                "email": "student@bu.edu",
            }
        },
        "What requirements do I need for my master's program?",
    )

    assert "bu.edu" in domains


def test_trace_summary_reports_completed_blocked_and_source_counts():
    trace = summarize_trace(
        {
            "target_entity": {"kind": "program", "program": "Computer Science"},
            "workflow": "academic_planning",
            "task_graph": [
                {"id": "load_student_state", "status": "completed"},
                {"id": "retrieve_primary_sources", "status": "blocked"},
            ],
            "working_memory": {
                "source_audit": [
                    {"action": "selected"},
                    {"action": "selected"},
                    {"action": "rejected"},
                ]
            },
            "blocked_reasons": ["No live schedule source was found."],
            "web_results": [{"url": "https://catalog.csus.edu"}],
            "profile_data": {"personal": {"name": "Sagar"}},
            "evidence_records": [{"entity_type": "course"}],
            "decision_payload": {"decision_type": "course_planning"},
            "confidence_score": 0.7,
        }
    )

    assert trace["completed_tasks"] == ["load_student_state"]
    assert trace["blocked_tasks"] == ["retrieve_primary_sources"]
    assert trace["selected_sources"] == 2
    assert trace["rejected_sources"] == 1


def test_eligibility_reasoner_builds_structured_known_assumed_missing_output():
    summary = {
        "completed_courses": {"value": ["CSC 201"]},
        "assumptions": [],
    }
    evidence = [
        {
            "source_type": "degree_page",
            "entity_type": "requirement",
            "value": {"summary": "Requires fully classified status"},
            "source_url": "https://catalog.csus.edu/ms",
            "source_title": "MS in Computer Science",
            "excerpt": "Students must be fully classified.",
        },
        {
            "source_type": "degree_page",
            "entity_type": "program_constraint",
            "value": {"summary": "Prerequisite completion may be required"},
            "source_url": "https://catalog.csus.edu/ms",
            "source_title": "MS in Computer Science",
            "excerpt": "Students with deficiencies may need to remove them.",
        },
    ]

    payload = _heuristic_eligibility_payload(summary, group_evidence_records(evidence, {}))

    assert payload["decision_type"] == "eligibility_check"
    assert payload["recommended_items"]
    assert payload["blocked_or_uncertain_items"]


def test_compacted_session_preserves_student_state_for_follow_ups():
    summary = {
        "institution": {"value": "Boston University", "source": "user"},
        "program": {"value": "Data Science", "source": "user"},
        "goals": {"value": ["product manager"], "source": "conversation"},
        "preferences": {"value": ["remote"], "source": "conversation"},
        "assumptions": [],
        "current_skills": {"value": ["SQL"], "source": "profile"},
        "recent_decisions": {"value": ["Apply for internship"], "source": "conversation"},
    }
    compacted = compact_session_state(summary, {"planner_blockers": ["Need transcript"]})

    assert compacted["stable_facts"]["institution"] == "Boston University"
    assert compacted["stable_facts"]["program"] == "Data Science"
    assert "product manager" in compacted["evolving_goals"]
    assert "Need transcript" in compacted["unresolved_blockers"]
