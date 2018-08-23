# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import absolute_import
from __future__ import unicode_literals

from compare_locales.tests.test_checks import BaseHelper
from compare_locales.paths import File


ANDROID_WRAPPER = b'''<?xml version="1.0" encoding="utf-8"?>
<resources>
  <string name="foo">%s</string>
</resources>
'''


class QuotesTest(BaseHelper):
    file = File('values/strings.xml', 'values/strings.xml')
    refContent = ANDROID_WRAPPER % b'plain'

    def test_straightquotes(self):
        self._test(
            ANDROID_WRAPPER % b'""',
            (
                (
                    "error",
                    0,
                    "Double straight quotes not allowed",
                    "android"
                ),
            )
        )
        self._test(
            ANDROID_WRAPPER % b'"some"',
            tuple()
        )
        self._test(
            ANDROID_WRAPPER % b'some\\"',
            tuple()
        )
        self._test(
            ANDROID_WRAPPER % b'some"',
            tuple()
        )
        self._test(
            ANDROID_WRAPPER % b'some',
            tuple()
        )
        self._test(
            ANDROID_WRAPPER % b'some""',
            (
                (
                    "error",
                    4,
                    "Double straight quotes not allowed",
                    "android"
                ),
            )
        )

    def test_apostrophes(self):
        self._test(
            ANDROID_WRAPPER % b'''"some'apos"''',
            tuple()
        )
        self._test(
            ANDROID_WRAPPER % b'''some\\'apos''',
            tuple()
        )
        self._test(
            ANDROID_WRAPPER % b'''some'apos''',
            (
                (
                    "error",
                    4,
                    "Apostrophe must be escaped",
                    "android"
                ),
            )
        )


class TranslatableTest(BaseHelper):
    file = File('values/strings.xml', 'values/strings.xml')
    refContent = (ANDROID_WRAPPER % b'plain').replace(
        b'name="foo"',
        b'translatable="false" name="foo"')

    def test_translatable(self):
        self._test(
            ANDROID_WRAPPER % b'"some"',
            (
                (
                    "error",
                    0,
                    "strings must be translatable",
                    "android"
                ),
            )
        )


class PrintfSTest(BaseHelper):
    file = File('values/strings.xml', 'values/strings.xml')
    refContent = ANDROID_WRAPPER % b'%s'

    def test_match(self):
        self._test(
            ANDROID_WRAPPER % b'"%s"',
            tuple()
        )
        self._test(
            ANDROID_WRAPPER % b'"%1$s"',
            tuple()
        )
        self._test(
            ANDROID_WRAPPER % b'"$s %1$s"',
            tuple()
        )
        self._test(
            ANDROID_WRAPPER % b'"$1$s %1$s"',
            tuple()
        )

    def test_mismatch(self):
        self._test(
            ANDROID_WRAPPER % b'"%d"',
            (
                (
                    "error",
                    0,
                    "Mismatching formatter",
                    "android"
                ),
            )
        )

    def test_off_position(self):
        self._test(
            ANDROID_WRAPPER % b'%2$s',
            (
                (
                    "error",
                    0,
                    "Formatter %2$s not found in reference",
                    "android"
                ),
            )
        )


class PrintfDTest(BaseHelper):
    file = File('values/strings.xml', 'values/strings.xml')
    refContent = ANDROID_WRAPPER % b'%d'

    def test_match(self):
        self._test(
            ANDROID_WRAPPER % b'"%d"',
            tuple()
        )
        self._test(
            ANDROID_WRAPPER % b'"%1$d"',
            tuple()
        )
        self._test(
            ANDROID_WRAPPER % b'"$d %1$d"',
            tuple()
        )
        self._test(
            ANDROID_WRAPPER % b'"$1$d %1$d"',
            tuple()
        )

    def test_mismatch(self):
        self._test(
            ANDROID_WRAPPER % b'"%s"',
            (
                (
                    "error",
                    0,
                    "Mismatching formatter",
                    "android"
                ),
            )
        )

    def test_off_position(self):
        self._test(
            ANDROID_WRAPPER % b'%2$d',
            (
                (
                    "error",
                    0,
                    "Formatter %2$d not found in reference",
                    "android"
                ),
            )
        )
