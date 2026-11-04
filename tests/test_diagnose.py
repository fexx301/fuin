import base64
import json

from fuin import diagnose as D

NUM = {"answer_type": "numeric", "answer": "10"}
EX = {"answer_type": "exact", "answer": "ft_on_transfer", "accept": ["ft_on_transfer()"]}


def resp(content, finish="stop"):
    return base64.b64encode(json.dumps({"choices": [{"finish_reason": finish, "message": {"content": content}}]}).encode()).decode()


def test_classes():
    assert D.classify(NUM, resp("10"), 1) == "correct"
    assert D.classify(NUM, resp("**10%**"), 0) == "format"
    assert D.classify(NUM, resp("about 10 percent"), 0) == "format"
    assert D.classify(NUM, resp("4.5"), 0) == "wrong"
    assert D.classify(NUM, resp("between 10 and 20"), 0) == "wrong"  # two numbers: not a clean match
    assert D.classify(NUM, resp("", "length"), 0) == "cut off"
    assert D.classify(EX, resp("The method is `ft_on_transfer`."), 0) == "format"
    assert D.classify(EX, resp("ft_resolve_transfer"), 0) == "wrong"
