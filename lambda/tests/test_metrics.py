import json
import metrics


def test_emf_has_aws_key(capsys):
    metrics.emit_request_metrics("test-fn", 100, 50)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "_aws" in data


def test_emf_namespace(capsys):
    metrics.emit_request_metrics("test-fn", 100, 50)
    out = capsys.readouterr().out
    data = json.loads(out)
    cw = data["_aws"]["CloudWatchMetrics"][0]
    assert cw["Namespace"] == "personal-chat-app/Chat"


def test_emf_dimensions_only_function_name(capsys):
    metrics.emit_request_metrics("test-fn", 100, 50)
    out = capsys.readouterr().out
    data = json.loads(out)
    cw = data["_aws"]["CloudWatchMetrics"][0]
    all_dims = [dim for dim_set in cw["Dimensions"] for dim in dim_set]
    assert all_dims == ["FunctionName"]


def test_emf_no_extra_dimension_keys(capsys):
    metrics.emit_request_metrics("my-function", 200, 100)
    out = capsys.readouterr().out
    data = json.loads(out)
    allowed_top_keys = {"_aws", "FunctionName", "InputTokens", "OutputTokens"}
    assert set(data.keys()) == allowed_top_keys


def test_emf_no_request_count(capsys):
    metrics.emit_request_metrics("fn", 10, 20)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "RequestCount" not in data
    cw = data["_aws"]["CloudWatchMetrics"][0]
    metric_names = [m["Name"] for m in cw["Metrics"]]
    assert "RequestCount" not in metric_names


def test_emf_function_name_value(capsys):
    metrics.emit_request_metrics("my-function", 100, 50)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["FunctionName"] == "my-function"


def test_emf_input_tokens_value(capsys):
    metrics.emit_request_metrics("fn", 123, 42)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["InputTokens"] == 123


def test_emf_output_tokens_value(capsys):
    metrics.emit_request_metrics("fn", 123, 42)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["OutputTokens"] == 42


def test_emf_metric_names(capsys):
    metrics.emit_request_metrics("fn", 10, 20)
    out = capsys.readouterr().out
    data = json.loads(out)
    cw = data["_aws"]["CloudWatchMetrics"][0]
    metric_names = [m["Name"] for m in cw["Metrics"]]
    assert "InputTokens" in metric_names
    assert "OutputTokens" in metric_names
