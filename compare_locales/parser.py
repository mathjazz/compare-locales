# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import re
import bisect
import codecs
import logging

__constructors = []


class Entity(object):
    '''
    Abstraction layer for a localizable entity.
    Currently supported are grammars of the form:

    1: pre white space
    2: pre comments
    3: entity definition
    4: entity key (name)
    5: entity value
    6: post comment (and white space) in the same line (dtd only)
                                                 <--[1]
    <!-- pre comments -->                        <--[2]
    <!ENTITY key "value"> <!-- comment -->

    <-------[3]---------><------[6]------>
    '''
    def __init__(self, ctx, pp,
                 span, pre_ws_span, pre_comment_span, def_span,
                 key_span, val_span, post_span):
        self.ctx = ctx
        self.span = span
        self.pre_ws_span = pre_ws_span
        self.pre_comment_span = pre_comment_span
        self.def_span = def_span
        self.key_span = key_span
        self.val_span = val_span
        self.post_span = post_span
        self.pp = pp
        pass

    def position(self, offset=0):
        """Get the 1-based line and column of the character
        with given offset into the Entity.

        If offset is negative, return the end of the Entity.
        """
        if offset < 0:
            pos = self.span[1]
        else:
            pos = self.span[0] + offset
        return self.ctx.lines(pos)[0]

    def value_position(self, offset=0):
        """Get the 1-based line and column of the character
        with given offset into the value.

        If offset is negative, return the end of the value.
        """
        if offset < 0:
            pos = self.val_span[1]
        else:
            pos = self.val_span[0] + offset
        return self.ctx.lines(pos)[0]

    # getter helpers

    def get_all(self):
        return self.ctx.contents[self.span[0]:self.span[1]]

    def get_pre_ws(self):
        return self.ctx.contents[self.pre_ws_span[0]:self.pre_ws_span[1]]

    def get_pre_comment(self):
        return self.ctx.contents[self.pre_comment_span[0]:
                                 self.pre_comment_span[1]]

    def get_def(self):
        return self.ctx.contents[self.def_span[0]:self.def_span[1]]

    def get_key(self):
        return self.ctx.contents[self.key_span[0]:self.key_span[1]]

    def get_val(self):
        return self.pp(self.ctx.contents[self.val_span[0]:self.val_span[1]])

    def get_raw_val(self):
        return self.ctx.contents[self.val_span[0]:self.val_span[1]]

    def get_post(self):
        return self.ctx.contents[self.post_span[0]:self.post_span[1]]

    # getters

    all = property(get_all)
    pre_ws = property(get_pre_ws)
    pre_comment = property(get_pre_comment)
    definition = property(get_def)
    key = property(get_key)
    val = property(get_val)
    raw_val = property(get_raw_val)
    post = property(get_post)

    def __repr__(self):
        return self.key


class Junk(object):
    '''
    An almost-Entity, representing junk data that we didn't parse.
    This way, we can signal bad content as stuff we don't understand.
    And the either fix that, or report real bugs in localizations.
    '''
    junkid = 0

    def __init__(self, ctx, span):
        self.ctx = ctx
        self.span = span
        self.pre_ws = self.pre_comment = self.definition = self.post = ''
        self.__class__.junkid += 1
        self.key = '_junk_%d_%d-%d' % (self.__class__.junkid, span[0], span[1])

    def position(self, offset=0):
        """Get the 1-based line and column of the character
        with given offset into the Entity.

        If offset is negative, return the end of the Entity.
        """
        if offset < 0:
            pos = self.span[1]
        else:
            pos = self.span[0] + offset
        return self.ctx.lines(pos)[0]

    # getter helpers
    def get_all(self):
        return self.ctx.contents[self.span[0]:self.span[1]]

    # getters
    all = property(get_all)
    val = property(get_all)

    def __repr__(self):
        return self.key


class Parser:
    canMerge = True

    class Context(object):
        "Fixture for content and line numbers"
        def __init__(self, contents):
            self.contents = contents
            self._lines = None

        def lines(self, *positions):
            # return line and column tuples, 1-based
            if self._lines is None:
                nl = re.compile('\n', re.M)
                self._lines = [m.end()
                               for m in nl.finditer(self.contents)]
            line_nrs = [bisect.bisect(self._lines, p) for p in positions]
            # compute columns
            pos_ = [
                (1 + line, 1 + p - (self._lines[line-1] if line else 0))
                for line, p in zip(line_nrs, positions)]
            return pos_

    def __init__(self):
        if not hasattr(self, 'encoding'):
            self.encoding = 'utf-8'
        self.ctx = None

    def readFile(self, file):
        f = codecs.open(file, 'r', self.encoding)
        try:
            self.ctx = Parser.Context(f.read())
        except UnicodeDecodeError, e:
            (logging.getLogger('locales')
                    .error("Can't read file: " + file + '; ' + str(e)))
        f.close()

    def readContents(self, contents):
        (contents, length) = codecs.getdecoder(self.encoding)(contents)
        self.ctx = Parser.Context(contents)

    def parse(self):
        l = []
        m = {}
        for e in self:
            m[e.key] = len(l)
            l.append(e)
        return (l, m)

    def postProcessValue(self, val):
        return val

    def __iter__(self):
        ctx = self.ctx
        contents = ctx.contents
        offset = 0
        self.header, offset = self.getHeader(contents, offset)
        self.footer = ''
        entity, offset = self.getEntity(ctx, offset)
        while entity:
            yield entity
            entity, offset = self.getEntity(ctx, offset)
        f = self.reFooter.match(contents, offset)
        if f:
            self.footer = f.group()
            offset = f.end()
        if len(contents) > offset:
            yield Junk(ctx, (offset, len(contents)))
        pass

    def getHeader(self, contents, offset):
        header = ''
        h = self.reHeader.match(contents)
        if h:
            header = h.group()
            offset = h.end()
        return (header, offset)

    def getEntity(self, ctx, offset):
        m = self.reKey.match(ctx.contents, offset)
        if m:
            offset = m.end()
            entity = self.createEntity(ctx, m)
            return (entity, offset)
        # first check if footer has a non-empty match,
        # 'cause then we don't find junk
        m = self.reFooter.match(ctx.contents, offset)
        if m and m.end() > offset:
            return (None, offset)
        m = self.reKey.search(ctx.contents, offset)
        if m:
            # we didn't match, but search, so there's junk between offset
            # and start. We'll match() on the next turn
            junkend = m.start()
            return (Junk(ctx, (offset, junkend)), junkend)
        return (None, offset)

    def createEntity(self, ctx, m):
        return Entity(ctx, self.postProcessValue,
                      *[m.span(i) for i in xrange(7)])


def getParser(path):
    for item in __constructors:
        if re.search(item[0], path):
            return item[1]
    raise UserWarning("Cannot find Parser")


# Subgroups of the match will:
# 1: pre white space
# 2: pre comments
# 3: entity definition
# 4: entity key (name)
# 5: entity value
# 6: post comment (and white space) in the same line (dtd only)
#                                            <--[1]
# <!-- pre comments -->                      <--[2]
# <!ENTITY key "value"> <!-- comment -->
#
# <-------[3]---------><------[6]------>


class DTDParser(Parser):
    # http://www.w3.org/TR/2006/REC-xml11-20060816/#NT-NameStartChar
    # ":" | [A-Z] | "_" | [a-z] |
    # [#xC0-#xD6] | [#xD8-#xF6] | [#xF8-#x2FF] | [#x370-#x37D] | [#x37F-#x1FFF]
    # | [#x200C-#x200D] | [#x2070-#x218F] | [#x2C00-#x2FEF] |
    # [#x3001-#xD7FF] | [#xF900-#xFDCF] | [#xFDF0-#xFFFD] |
    # [#x10000-#xEFFFF]
    CharMinusDash = u'\x09\x0A\x0D\u0020-\u002C\u002E-\uD7FF\uE000-\uFFFD'
    XmlComment = '<!--(?:-?[%s])*?-->' % CharMinusDash
    NameStartChar = u':A-Z_a-z\xC0-\xD6\xD8-\xF6\xF8-\u02FF' + \
        u'\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F' + \
        u'\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD'
    # + \U00010000-\U000EFFFF seems to be unsupported in python

    # NameChar ::= NameStartChar | "-" | "." | [0-9] | #xB7 |
    #     [#x0300-#x036F] | [#x203F-#x2040]
    NameChar = NameStartChar + ur'\-\.0-9' + u'\xB7\u0300-\u036F\u203F-\u2040'
    Name = '[' + NameStartChar + '][' + NameChar + ']*'
    reKey = re.compile('(?:(?P<pre>\s*)(?P<precomment>(?:' + XmlComment +
                       '\s*)*)(?P<entity><!ENTITY\s+(?P<key>' + Name +
                       ')\s+(?P<val>\"[^\"]*\"|\'[^\']*\'?)\s*>)'
                       '(?P<post>[ \t]*(?:' + XmlComment + '\s*)*\n?)?)',
                       re.DOTALL)
    # add BOM to DTDs, details in bug 435002
    reHeader = re.compile(u'^\ufeff?'
                          u'(\s*<!--.*(http://mozilla.org/MPL/2.0/|'
                          u'LICENSE BLOCK)([^-]+-)*[^-]+-->)?', re.S)
    reFooter = re.compile('\s*(<!--([^-]+-)*[^-]+-->\s*)*$')
    rePE = re.compile('(?:(\s*)((?:' + XmlComment + '\s*)*)'
                      '(<!ENTITY\s+%\s+(' + Name +
                      ')\s+SYSTEM\s+(\"[^\"]*\"|\'[^\']*\')\s*>\s*%' + Name +
                      ';)([ \t]*(?:' + XmlComment + '\s*)*\n?)?)')

    def getEntity(self, ctx, offset):
        '''
        Overload Parser.getEntity to special-case ParsedEntities.
        Just check for a parsed entity if that method claims junk.

        <!ENTITY % foo SYSTEM "url">
        %foo;
        '''
        entity, inneroffset = Parser.getEntity(self, ctx, offset)
        if (entity and isinstance(entity, Junk)) or entity is None:
            m = self.rePE.match(ctx.contents, offset)
            if m:
                inneroffset = m.end()
                entity = Entity(ctx, self.postProcessValue,
                                *[m.span(i) for i in xrange(7)])
        return (entity, inneroffset)

    def createEntity(self, ctx, m):
        valspan = m.span('val')
        valspan = (valspan[0]+1, valspan[1]-1)
        return Entity(ctx, self.postProcessValue, m.span(),
                      m.span('pre'), m.span('precomment'),
                      m.span('entity'), m.span('key'), valspan,
                      m.span('post'))


class PropertiesParser(Parser):
    escape = re.compile(r'\\((?P<uni>u[0-9a-fA-F]{1,4})|'
                        '(?P<nl>\n\s*)|(?P<single>.))', re.M)
    known_escapes = {'n': '\n', 'r': '\r', 't': '\t', '\\': '\\'}

    def __init__(self):
        self.reKey = re.compile('^(\s*)'
                                '((?:[#!].*?\n\s*)*)'
                                '([^#!\s\n][^=:\n]*?)\s*[:=][ \t]*', re.M)
        self.reHeader = re.compile('^\s*([#!].*\s*)+')
        self.reFooter = re.compile('\s*([#!].*\s*)*$')
        self._escapedEnd = re.compile(r'\\+$')
        self._trailingWS = re.compile(r'[ \t]*$')
        Parser.__init__(self)

    def getHeader(self, contents, offset):
        header = ''
        h = self.reHeader.match(contents, offset)
        if h:
            candidate = h.group()
            if 'http://mozilla.org/MPL/2.0/' in candidate or \
                    'LICENSE BLOCK' in candidate:
                header = candidate
                offset = h.end()
        return (header, offset)

    def getEntity(self, ctx, offset):
        # overwritten to parse values line by line
        contents = ctx.contents
        m = self.reKey.match(contents, offset)
        if m:
            offset = m.end()
            while True:
                endval = nextline = contents.find('\n', offset)
                if nextline == -1:
                    endval = offset = len(contents)
                    break
                # is newline escaped?
                _e = self._escapedEnd.search(contents, offset, nextline)
                offset = nextline + 1
                if _e is None:
                    break
                # backslashes at end of line, if 2*n, not escaped
                if len(_e.group()) % 2 == 0:
                    break
            # strip trailing whitespace
            ws = self._trailingWS.search(contents, m.end(), offset)
            if ws:
                endval -= ws.end() - ws.start()
            entity = Entity(ctx, self.postProcessValue,
                            (m.start(), offset),   # full span
                            m.span(1),  # leading whitespan
                            m.span(2),  # leading comment span
                            (m.start(3), offset),   # entity def span
                            m.span(3),   # key span
                            (m.end(), endval),   # value span
                            (offset, offset))  # post comment span, empty
            return (entity, offset)
        m = self.reKey.search(contents, offset)
        if m:
            # we didn't match, but search, so there's junk between offset
            # and start. We'll match() on the next turn
            junkend = m.start()
            return (Junk(ctx, (offset, junkend)), junkend)
        return (None, offset)

    def postProcessValue(self, val):

        def unescape(m):
            found = m.groupdict()
            if found['uni']:
                return unichr(int(found['uni'][1:], 16))
            if found['nl']:
                return ''
            return self.known_escapes.get(found['single'], found['single'])
        val = self.escape.sub(unescape, val)
        return val


class DefinesParser(Parser):
    # can't merge, #unfilter needs to be the last item, which we don't support
    canMerge = False

    def __init__(self):
        self.reKey = re.compile('^(\s*)((?:^#(?!define\s).*\s*)*)'
                                '(#define[ \t]+(\w+)[ \t]+(.*?))([ \t]*$\n?)',
                                re.M)
        self.reHeader = re.compile('^\s*(#(?!define\s).*\s*)*')
        self.reFooter = re.compile('\s*(#(?!define\s).*\s*)*$', re.M)
        Parser.__init__(self)


class IniParser(Parser):
    '''
    Parse files of the form:
    # initial comment
    [cat]
    whitespace*
    #comment
    string=value
    ...
    '''
    def __init__(self):
        self.reHeader = re.compile('^((?:\s*|[;#].*)\n)*\[.+?\]\n', re.M)
        self.reKey = re.compile('(\s*)((?:[;#].*\n\s*)*)((.+?)=(.*))(\n?)')
        self.reFooter = re.compile('\s*([;#].*\s*)*$')
        Parser.__init__(self)


__constructors = [('\\.dtd$', DTDParser()),
                  ('\\.properties$', PropertiesParser()),
                  ('\\.ini$', IniParser()),
                  ('\\.inc$', DefinesParser())]
