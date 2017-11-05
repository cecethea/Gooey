"""
Converts argparse parser actions into json "Build Specs"
"""
import pprint
import argparse
import os
import sys
from argparse import (
    _CountAction,
    _HelpAction,
    _StoreConstAction,
    _StoreFalseAction,
    _StoreTrueAction,
    _SubParsersAction)
from collections import OrderedDict
from functools import partial

VALID_WIDGETS = (
    'FileChooser',
    'MultiFileChooser',
    'FileSaver',
    'DirChooser',
    'DateChooser',
    'TextField',
    'Dropdown',
    'Counter',
    'RadioGroup',
    'CheckBox',
    'MultiDirChooser',
    'Textarea',
    'PasswordField',
    'Listbox'
)


class UnknownWidgetType(Exception):
    pass


class UnsupportedConfiguration(Exception):
    pass


def convert(parser):
    assert_subparser_constraints(parser)

    x = {
        'layout': 'standard',
        'widgets': OrderedDict(
            (choose_name(name, sub_parser), {
                'command': name,
                'contents': process(sub_parser, getattr(sub_parser, 'widgets', {}))
            }) for name, sub_parser in iter_parsers(parser))
    }
    pprint.pprint(x)
    import sys
    sys.exit(0)
    return x

def assert_subparser_constraints(parser):
    if has_subparsers(parser._actions):
        if has_required(parser._actions):
            raise UnsupportedConfiguration(
                "Gooey doesn't currently support top level required arguments "
                "when subparsers are present.")

def iter_parsers(parser):
    try:
        return get_subparser(parser._actions).choices.items()
    except:
        return iter([('primary', parser)])

def extract_groups(action_group):
    '''
    Recursively extract argument groups and associated actions
    from ParserGroup objects
    '''
    return {
        'name': action_group.title,
        'description': '',
        'items': [action for action in action_group._group_actions
                  if not is_help_message(action)],
        'groups': [extract_groups(group) for group in action_group._action_groups]
    }


def contains_actions(a, b):
    ''' check if any actions(a) are present in actions(b) '''
    return set(a).intersection(set(b))


def reapply_mutex_groups(mutex_groups, action_groups):
    # argparse stores mutually exclusive groups independently
    # of all other groups. So, they must be manually re-combined
    # with the groups/subgroups to which they were originally declared
    # in order to have them appear in the correct location in the UI.
    #
    # Order is attempted to be preserved by inserting the MutexGroup
    # into the _actions list at the first occurrence of any item
    # where the two groups intersect
    def swap_actions(actions):
        for mutexgroup in mutex_groups:
            mutex_actions = mutexgroup._group_actions
            if contains_actions(mutex_actions, actions):
                # make a best guess as to where we should store the group
                targetindex = actions.index(mutexgroup._group_actions[0])
                # insert the _ArgumentGroup container
                actions[targetindex] = mutexgroup
                # remove the duplicated individual actions
                return [action for action in actions
                        if action not in mutex_actions]
        return actions

    return [group.update({'items': swap_actions(group['items'])}) or group
            for group in action_groups]


def process(parser, widget_dict):
    mutex_groups = parser._mutually_exclusive_groups
    raw_action_groups = [extract_groups(group) for group in parser._action_groups]
    corrected_action_groups = reapply_mutex_groups(mutex_groups, raw_action_groups)

    return categorize2(corrected_action_groups, widget_dict)


def categorize2(groups, widget_dict):
    return [{
        'name': group['name'],
        'items': list(categorize(group['items'], widget_dict)),
        'groups': categorize2(group['groups'], widget_dict),
        'description': group['description']
    } for group in groups]


def categorize(actions, widget_dict, required=False):
    _get_widget = partial(get_widget, widgets=widget_dict)
    for action in actions:
        if is_mutex(action):
            build_radio_group(action, widget_dict)
        elif is_standard(action):
            yield as_json(action, _get_widget(action) or 'TextField', required)
        elif is_choice(action):
            yield as_json(action, _get_widget(action) or 'Dropdown', required)
        elif is_flag(action):
            yield as_json(action, _get_widget(action) or 'CheckBox', required)
        elif is_counter(action):
            _json = as_json(action, _get_widget(action) or 'Counter', required)
            # pre-fill the 'counter' dropdown
            _json['data']['choices'] = list(map(str, range(1, 11)))
            yield _json
        else:
            raise UnknownWidgetType(action)


def get_widget(action, widgets):
    supplied_widget = widgets.get(action.dest, None)
    type_arg_widget = 'FileChooser' if action.type == argparse.FileType else None
    return supplied_widget or type_arg_widget or None


def is_required(action):
    '''
    _actions possessing the `required` flag and not implicitly optional
    through `nargs` being '*' or '?'
    '''
    return not isinstance(action, _SubParsersAction) and (
    action.required == True and action.nargs not in ['*', '?'])


def is_mutex(action):
    return isinstance(action, argparse._MutuallyExclusiveGroup)


def has_required(actions):
    return list(filter(None, list(filter(is_required, actions))))


def is_subparser(action):
    return isinstance(action, _SubParsersAction)


def has_subparsers(actions):
    return list(filter(is_subparser, actions))


def get_subparser(actions):
    return list(filter(is_subparser, actions))[0]


def is_optional(action):
    '''
    _actions either not possessing the `required` flag or implicitly optional through `nargs` being '*' or '?'
    '''
    return (not action.required) or action.nargs in ['*', '?']


def is_choice(action):
    ''' action with choices supplied '''
    return action.choices


def is_standard(action):
    """ actions which are general "store" instructions.
    e.g. anything which has an argument style like:
       $ script.py -f myfilename.txt
    """
    boolean_actions = (
        _StoreConstAction, _StoreFalseAction,
        _StoreTrueAction
    )
    return (not action.choices
            and not isinstance(action, _CountAction)
            and not isinstance(action, _HelpAction)
            and type(action) not in boolean_actions)


def is_flag(action):
    """ _actions which are either storeconst, store_bool, etc.. """
    action_types = [_StoreTrueAction, _StoreFalseAction, _StoreConstAction]
    return any(list(map(lambda Action: isinstance(action, Action), action_types)))


def is_counter(action):
    """ _actions which are of type _CountAction """
    return isinstance(action, _CountAction)


def is_default_progname(name, subparser):
    return subparser.prog == '{} {}'.format(os.path.split(sys.argv[0])[-1], name)


def is_help_message(action):
    return isinstance(action, _HelpAction)


def choose_name(name, subparser):
    return name if is_default_progname(name, subparser) else subparser.prog


def build_radio_group(mutex_group, widget_group):
  return {
    'type': 'RadioGroup',
    'group_name': 'Choose Option',
    'required': mutex_group.required,
    'data': {
      'commands': [action.option_strings for action in mutex_group._group_actions],
      'widgets': [categorize(action, widget_group)
                  for action in mutex_group._group_actions]
    }
  }



def as_json(action, widget, required):
    if widget not in VALID_WIDGETS:
        raise UnknownWidgetType('Widget Type {0} is unrecognized'.format(widget))

    return {
        'type': widget,
        'required': required,
        'data': {
            'display_name': action.metavar or action.dest,
            'help': action.help,
            'nargs': action.nargs or '',
            'commands': action.option_strings,
            'choices': action.choices or [],
            'default': clean_default(widget, action.default)
        }
    }


def clean_default(widget_type, default):
    '''
    Attemps to safely coalesce the default value down to
    a valid JSON type.

    See: Issue #147.
    function references supplied as arguments to the
    `default` parameter in Argparse cause errors in Gooey.
    '''
    if widget_type != 'CheckBox':
        return default.__name__ if callable(default) else default
    # checkboxes must be handled differently, as they
    # must be forced down to a boolean value
    return default if isinstance(default, bool) else False
