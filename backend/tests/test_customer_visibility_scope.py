import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import _filter_customers_for_user_scope  # noqa: E402


CUSTOMERS = [
    {
        "company_id": "owned-by-csm",
        "company_name": "责任客户成功客户",
        "csm": "张三",
        "service_manyi": [],
        "raw": {"success": {"name": "张三"}},
    },
    {
        "company_id": "owned-by-service",
        "company_name": "服务侧满一客户",
        "csm": "李四",
        "service_manyi": ["张三"],
        "raw": {"服务侧满一": [{"name": "张三"}]},
    },
    {
        "company_id": "not-owned",
        "company_name": "不可见客户",
        "csm": "李四",
        "service_manyi": ["王五"],
        "raw": {"success": {"name": "李四"}, "服务侧满一": {"name": "王五"}},
    },
]


def test_user_can_see_customer_when_responsible_csm_or_service_manyi_matches():
    visible = _filter_customers_for_user_scope(
        CUSTOMERS,
        {"source": "user", "display_name": "张三"},
    )

    assert [item["company_id"] for item in visible] == ["owned-by-csm", "owned-by-service"]


def test_sso_user_can_see_customer_when_service_manyi_matches_raw_field():
    visible = _filter_customers_for_user_scope(
        [
            {
                "company_id": "raw-service-owner",
                "company_name": "原始字段服务侧满一客户",
                "csm": "李四",
                "raw": {"服务侧满一": {"name": "张三"}},
            },
            {
                "company_id": "not-owned",
                "company_name": "不可见客户",
                "csm": "李四",
                "raw": {"服务侧满一": {"name": "王五"}},
            },
        ],
        {"source": "sso", "user_name": "张三"},
    )

    assert [item["company_id"] for item in visible] == ["raw-service-owner"]


def test_superadmin_customer_scope_is_unfiltered():
    visible = _filter_customers_for_user_scope(CUSTOMERS, {"source": "superadmin"})

    assert visible == CUSTOMERS
