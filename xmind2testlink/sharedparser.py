from xmindparser import xmind_to_dict, config

from .datatype import *

config['hideEmptyValue'] = False
_config = {'sep': ' ',
           'valid_sep': '/>-+',
           'precondition_sep': '\n----\n',
           'summary_sep': '\n----\n'}


def ignore_filter(topics):
    """filter topics starts with !"""
    result = [t for t in topics if t['title'] and not t['title'].startswith('!')]

    for topic in result:
        more_topics = topic.get('topics', [])
        topic['topics'] = ignore_filter(more_topics)

    return result


def open_and_cache_xmind(xmind_file):
    if not cache:
        cache['sheet'] = xmind_to_dict(xmind_file)
        cache['root'] = get_default_sheet(cache['sheet'])['topic']
        root_topics = cache['root'].get('topics', [])
        assert len(root_topics) > 0, "Invalid Xmind, should have at least 1 topic!"
        cache['root']['topics'] = ignore_filter(root_topics)
        cache['name'] = xmind_file

    get_logger().debug('Cached xmind: {}'.format(cache))


def get_default_sheet(sheets):
    """First sheet is the default sheet."""
    assert len(sheets) >= 0, 'Invalid xmind: should have at least 1 sheet!'
    return sheets[0]


def get_logger():
    from xmindparser import logger
    return logger


def flat_suite(suite):
    """Convert a suite object into flat testcase list."""
    tests = []

    for testcase in suite.testcase_list or []:
        d = testcase.to_dict()
        d['suite'] = suite.name
        tests.append(d)

    for sub_suite in suite.sub_suites or []:
        tests = tests + flat_suite(sub_suite)

    return tests


def flat_suite_old(suite):
    """Convert a suite object into flat testcase list."""
    tests = []

    for suite in suite.sub_suites:
        for test in suite.testcase_list:
            d = test.to_dict()
            d['suite'] = suite.name
            tests.append(d)

    return tests


def is_v2_format(d):
    """v2 xmind root dict will have a star maker, or sub node of testcase marked with priority."""
    if _is_v2_by_marker(d) or _is_v2_by_guess(d):
        _get_v2_sep(d)
        return True


def _get_v2_sep(d):
    """v2 sep is this last char of title."""
    last_char = d['title'][-1:]
    if last_char in _config['valid_sep']:
        cache['sep'] = last_char


def _is_v2_by_marker(d, maker_prefix='star'):
    """check if a node have a star maker"""
    if isinstance(d['makers'], list):
        for m in d['makers']:
            if m.startswith(maker_prefix):
                return True


def _is_v2_by_guess(d):
    """if any sub topic from testcase node mark with priority, this can be guessed as v2 xmind. """
    for suite_node in d['topics']:
        for testcase_node in suite_node['topics']:
            sub_topics = testcase_node['topics']
            while sub_topics:
                for _ in sub_topics:
                    temp_topics = []
                    if _is_v2_by_marker(_, maker_prefix='priority'):
                        return True
                    else:
                        temp_topics.extend(_['topics'])
                    sub_topics = temp_topics


def get_priority(d):
    if isinstance(d['makers'], list):
        for m in d['makers']:
            if m.startswith('priority'):
                return int(m[-1])


def get_execution_type(d):
    """
    support testcase option automation/manual by using "flag-green"
    :param d: testcase topic
    :return: 2 is automation, 1 is manual
    """
    #winter add to get automation flag "flag_green"
    if isinstance(d['makers'], list):
        if 'flag-green' in d['makers']:
                return 2
        return 1


def _filter_empty_value(values):
    result = [v for v in values if v]
    for r in result:
        if not isinstance(r, str):
            get_logger().error('Expected string but not: {}'.format(r))
    return [v.strip() for v in result]  # remove blank char in leading and trailing


def _filter_empty_comments(comment_values):
    """comment value like: [[{content:comment1},{content:comment2}],[...]]"""
    for comments in comment_values:
        for comment in comments:
            if comment.get('content'):
                yield comment['content']


def is_testcase_topic(d):
    priority = get_priority(d)

    if priority:
        return True

    child_node = d.get('topics', [])

    # if only one child topic and it is image or blank, consider parent is a test
    if len(child_node) == 1 and child_node[0]['title'] in ('[Image]', '[Blank]'):
        return True

    if child_node:
        return False

    return True


def build_testcase_title(nodes):
    values = [n['title'] for n in nodes]
    values = _filter_empty_value(values)

    # when sep is not blank, will add space around sep, e.g. '/' will be changed to ' / '
    sep = cache.get('sep', _config['sep'])
    if sep != ' ':
        sep = ' {} '.format(sep)

    return sep.join(values)


def build_testcase_precondition(nodes):
    values = (n['comment'] for n in nodes if n.get('comment', None))
    values = list(_filter_empty_comments(values))

    if not values:  # try to get from callout
        for n in nodes:
            for _ in n.get('callout', None) or []:
                values.append(_)

    comments = _filter_empty_value(values)
    return _config['precondition_sep'].join(comments)


def build_testcase_summary(nodes):
    values = [n['note'] for n in nodes]
    values = _filter_empty_value(values)
    return _config['summary_sep'].join(values)


def parse_step(step_dict):
    step = TestStep()
    step.action = step_dict['title']
    expected_node = step_dict.get('topics', None)

    if expected_node:
        step.expected = expected_node[0]['title']

    return step


def parse_steps(steps_dict):
    steps = []

    for step_number, step_node in enumerate(steps_dict, 1):
        step = parse_step(step_node)
        step.number = step_number
        steps.append(step)

    return steps


def parse_testcase(testcase_dict, parent=None):
    testcase = TestCase()
    nodes = parent + [testcase_dict] if parent else [testcase_dict]

    testcase.name = build_testcase_title(nodes)
    testcase.summary = build_testcase_summary(nodes)
    testcase.preconditions = build_testcase_precondition(nodes)
    testcase.importance = get_priority(testcase_dict)

    testcase.execution_type = get_execution_type(testcase_dict)


    steps_node = testcase_dict.get('topics', None)

    if steps_node:
        testcase.steps = parse_steps(steps_node)

    return testcase
