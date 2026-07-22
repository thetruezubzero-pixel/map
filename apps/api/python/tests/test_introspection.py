from app.agent_swarm.introspection import summarize_snapshot


def _base_snapshot(swarm_health):
    return {
        "db": {"entities_by_source_type": [], "agents_by_role_level": []},
        "swarm_health": swarm_health,
    }


def test_summarize_snapshot_notes_ungraduated_roles():
    snapshot = _base_snapshot(
        [
            {"role": "query_analyzer", "level": "amateur", "count": 2, "graduated_amateurs": 0},
            {"role": "result_synthesizer", "level": "amateur", "count": 2, "graduated_amateurs": 1},
        ]
    )
    summary = summarize_snapshot(snapshot)
    assert "no amateur graduations yet in: query_analyzer" in summary
    assert "result_synthesizer" not in summary.split("no amateur graduations yet in:")[1]


def test_summarize_snapshot_omits_note_when_no_amateurs_seeded():
    # count=0 means the role's amateurs were never seeded (e.g. all
    # promoted away) -- there's no shadow-training gap to flag, so the
    # note shouldn't fire on an empty roster the same way it would on a
    # populated-but-ungraduated one.
    snapshot = _base_snapshot([{"role": "query_analyzer", "level": "amateur", "count": 0, "graduated_amateurs": 0}])
    summary = summarize_snapshot(snapshot)
    assert "no amateur graduations" not in summary


def test_summarize_snapshot_omits_note_when_all_roles_graduated():
    snapshot = _base_snapshot(
        [
            {"role": "query_analyzer", "level": "amateur", "count": 2, "graduated_amateurs": 2},
            {"role": "result_synthesizer", "level": "amateur", "count": 2, "graduated_amateurs": 1},
        ]
    )
    summary = summarize_snapshot(snapshot)
    assert "no amateur graduations" not in summary
