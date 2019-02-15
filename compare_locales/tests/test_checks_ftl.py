# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import absolute_import
from __future__ import unicode_literals
import unittest

from .test_checks import BaseHelper
from compare_locales.paths import File


class TestFluent(BaseHelper):
    file = File('foo.ftl', 'foo.ftl')
    refContent = b'''\
simple = value
term_ref = some { -term }
msg-attr-ref = some {button.label}
'''

    def test_simple(self):
        self._test(b'''simple = localized''',
                   tuple())

    def test_missing_message_ref(self):
        self._test(b'''term_ref = localized''',
                   ((
                        u'warning', 0,
                        u'Missing message reference: -term', u'fluent'),
                    ))

    def test_l10n_only_message_ref(self):
        self._test(b'''simple = localized with { -term }''',
                   ((
                        u'warning', 26,
                        u'Obsolete message reference: -term', u'fluent'),
                    ))

    def test_message_ref(self):
        self._test(b'''term_ref = localized with { -term }''',
                   tuple())

    def test_term_attr(self):
        self._test(b'''term_ref = Depends on { -term.prop ->
    *[some] Term prop, doesn't reference the term value, though.
  }''',
                   ((
                       u'warning', 0,
                       u'Missing message reference: -term', u'fluent'),
                    ))

    def test_msg_attr(self):
        self._test(
            b'''msg-attr-ref = Nice {button.label}''',
            tuple()
        )
        self._test(
            b'''msg-attr-ref = not at all''',
            (
                (
                    'warning', 0,
                    'Missing message reference: button.label', 'fluent'
                ),
            )
        )
        self._test(
            b'''msg-attr-ref = {button} is not a label''',
            (
                (
                    'warning', 0,
                    'Missing message reference: button.label', 'fluent'
                ),
                (
                    'warning', 16,
                    'Obsolete message reference: button', 'fluent'
                ),
            )
        )
        self._test(
            b'''msg-attr-ref = {button.tooltip} is not a label''',
            (
                (
                    'warning', 0,
                    'Missing message reference: button.label', 'fluent'
                ),
                (
                    'warning', 16,
                    'Obsolete message reference: button.tooltip', 'fluent'
                ),
            )
        )

    def test_message_ref_variant(self):
        self._test(b'''term_ref = localized with { -term[variant] }''',
                   tuple())


if __name__ == '__main__':
    unittest.main()
