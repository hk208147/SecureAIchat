"""Project settings and the storage namespace for project chats and files."""

from uuid import uuid4

from boto3.dynamodb.conditions import Key

import research


def _key(sub, project_id):
    return {"pk": f"USER#{sub}", "sk": f"PROJECT#{research.checked_id(project_id)}"}


def _public(item):
    return {key: item[key] for key in ("id", "name", "persona_id")}


def get(table, sub, project_id):
    if table is None:
        raise research.ResearchError(503, "プロジェクトの保存先が利用できません。")
    item = table.get_item(Key=_key(sub, project_id), ConsistentRead=True).get("Item")
    if not item:
        raise research.ResearchError(404, "プロジェクトが見つかりません。")
    return _public(item)


def scope(table, sub, project_id):
    if project_id is None:
        return sub
    project = get(table, sub, project_id)
    return namespace(sub, project)


def namespace(sub, project):
    return f"{sub}#PROJECT#{project['id']}"


def list_projects(table, sub):
    args = {"KeyConditionExpression": Key("pk").eq(f"USER#{sub}") & Key("sk").begins_with("PROJECT#"),
            "ConsistentRead": True}
    items = []
    while True:
        page = table.query(**args)
        items.extend(_public(item) for item in page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return sorted(items, key=lambda item: (item["name"].casefold(), item["id"]))
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def create(table, sub, body):
    name = research.bounded_text(body.get("name"), 80, "Project name")
    project_id = str(uuid4())
    item = {**_key(sub, project_id), "id": project_id, "name": name, "persona_id": "default"}
    table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
    return _public(item)


def set_persona(table, sub, body):
    project_id = body.get("project_id")
    get(table, sub, project_id)
    persona_id = research.get_persona(table, sub, body.get("persona_id"))["id"]
    updated = table.update_item(
        Key=_key(sub, project_id), UpdateExpression="SET persona_id = :persona",
        ExpressionAttributeValues={":persona": persona_id},
        ConditionExpression="attribute_exists(pk)", ReturnValues="ALL_NEW",
    )
    return _public(updated["Attributes"])
