from app.services.operation_executor import MAX_LOG_WIDGET_NAME_LEN, _build_log_widget_name


def test_build_log_widget_name_keeps_short_value():
    change_items = [
        {"widget_name": "title"},
        {"widget_name": "solve_what_ques"},
    ]

    result = _build_log_widget_name(change_items)

    assert result == "title,solve_what_ques"


def test_build_log_widget_name_truncates_long_value_for_db_log():
    change_items = [
        {"widget_name": "title"},
        {"widget_name": "solve_what_ques"},
        {"widget_name": "solve_what_ans"},
        {"widget_name": "_widget_1744337240628"},
        {"widget_name": "_widget_1773296816191"},
        {"widget_name": "_widget_1773296816192"},
        {"widget_name": "_widget_1737340360281"},
    ]

    result = _build_log_widget_name(change_items)

    assert len(result) <= MAX_LOG_WIDGET_NAME_LEN
    assert result.startswith("title")
    assert "...(+" in result
