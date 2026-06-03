from evals.evaluator import Evaluator


def test_parse_score_response_accepts_plain_json():
    score = Evaluator._parse_score_response('{"score": 0.8, "reasoning": "Concise and relevant."}')

    assert score is not None
    assert score.score == 0.8
    assert score.reasoning == "Concise and relevant."


def test_parse_score_response_accepts_fenced_json():
    score = Evaluator._parse_score_response(
        '```json\n{"score": 0.25, "reasoning": "The answer is incomplete."}\n```'
    )

    assert score is not None
    assert score.score == 0.25
    assert score.reasoning == "The answer is incomplete."


