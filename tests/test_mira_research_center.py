import pytest
from unittest.mock import MagicMock, patch
from sqlmodel import Session, select
from utils.mira.ai_research_models import ResearchConversation, ResearchMessage
from utils.mira.ai_research import get_cache_key

def test_research_center_status_and_delete(client, session: Session):
    # 1. Arrange: Create a practitioner user first
    from models import User
    user = User(
        email="test_doc@gpconnect.nhs.uk",
        name="Test Doctor",
        role="practitioner",
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # Insert a conversation
    conv = ResearchConversation(
        id="test_conv_123",
        practitioner_id=user.id,
        title="Test Research",
        preview="No messages yet",
        status="Ongoing"
    )
    session.add(conv)
    session.commit()
    session.refresh(conv)

    # 2. Act: PATCH the status to Completed
    response = client.patch(
        f"/mira/research/conversations/{conv.id}/status",
        json={"status": "Completed"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Completed"
    assert data["status_reason"] is None

    # Check database
    session.refresh(conv)
    assert conv.status == "Completed"

    # 3. Act: PATCH the status to Failed with a reason
    response = client.patch(
        f"/mira/research/conversations/{conv.id}/status",
        json={"status": "Failed", "reason": "No relevant studies found"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Failed"
    assert data["status_reason"] == "No relevant studies found"

    # Check database
    session.refresh(conv)
    assert conv.status == "Failed"
    assert conv.status_reason == "No relevant studies found"

    # 4. Act: GET conversations and verify status is returned
    response = client.get(f"/mira/research/conversations?practitioner_id={user.id}")
    assert response.status_code == 200
    convs_list = response.json()
    assert len(convs_list) > 0
    assert convs_list[0]["status"] == "Failed"
    assert convs_list[0]["status_reason"] == "No relevant studies found"

    # 5. Act: DELETE conversation with a reason
    response = client.delete(
        f"/mira/research/conversations/{conv.id}?reason=Doctor requested delete"
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Conversation deleted successfully"

    # Check database (it should be deleted)
    deleted_conv = session.get(ResearchConversation, conv.id)
    assert deleted_conv is None

@patch("utils.mira.ai_research.redis_client")
def test_redis_cache_key_and_hitting(mock_redis_client):
    # Test cache key generation
    key1 = get_cache_key("Thyroidectomy in Lupus", [{"type": "pdf", "name": "report.pdf", "url": "http://example.com/pdf"}])
    key2 = get_cache_key("Thyroidectomy in Lupus", [{"type": "pdf", "name": "report.pdf", "url": "http://example.com/pdf"}])
    assert key1 == key2

    # Different inputs should yield different keys
    key3 = get_cache_key("Thyroidectomy in Lupus", [])
    assert key1 != key3

def test_case_history_endpoints(client, session: Session):
    from models import User
    from utils.mira.case_history.history import CaseHistory
    
    # 1. Arrange: Create a practitioner user
    user = User(
        email="history_doc@gpconnect.nhs.uk",
        name="History Doctor",
        role="practitioner",
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # 2. Arrange: Create case history entries
    history1 = CaseHistory(
        practitioner_id=user.id,
        conversation_id="conv_success_1",
        title="Successful Research",
        preview="Everything went well",
        status="Completed",
        messages_json='[{"role": "user", "content": "hello"}, {"role": "agent", "content": "hi"}]'
    )
    history2 = CaseHistory(
        practitioner_id=user.id,
        conversation_id="conv_deleted_2",
        title="Deleted Research",
        preview="This was deleted",
        status="Deleted",
        status_reason="User clicked delete",
        messages_json='[]'
    )
    session.add(history1)
    session.add(history2)
    session.commit()

    # 3. Act: GET case history list
    response = client.get(f"/mira/case-history?practitioner_id={user.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    
    # Verify status mapping
    statuses = {item["id"]: item["status"] for item in data}
    assert statuses["conv_success_1"] == "success"
    assert statuses["conv_deleted_2"] == "deleted"

    # 4. Act: GET filtered case history list (status=deleted)
    response_deleted = client.get(f"/mira/case-history?practitioner_id={user.id}&status=deleted")
    assert response_deleted.status_code == 200
    data_deleted = response_deleted.json()
    assert len(data_deleted) == 1
    assert data_deleted[0]["id"] == "conv_deleted_2"

    # 5. Act: GET case history details
    response_details = client.get(f"/mira/case-history/conv_success_1/details")
    assert response_details.status_code == 200
    details = response_details.json()
    assert details["title"] == "Successful Research"
    assert len(details["messages"]) == 2
    assert details["messages"][0]["role"] == "user"

