# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

'Mozilla l10n compare locales tool'

import codecs
import os
import shutil
import re
from collections import defaultdict

try:
    from json import dumps
except:
    from simplejson import dumps

from compare_locales import parser
from compare_locales import paths, mozpath
from compare_locales.checks import getChecker


class Tree(object):
    def __init__(self, valuetype):
        self.branches = dict()
        self.valuetype = valuetype
        self.value = None

    def __getitem__(self, leaf):
        parts = []
        if isinstance(leaf, paths.File):
            parts = [p for p in [leaf.locale, leaf.module] if p] + \
                leaf.file.split('/')
        else:
            parts = leaf.split('/')
        return self.__get(parts)

    def __get(self, parts):
        common = None
        old = None
        new = tuple(parts)
        t = self
        for k, v in self.branches.iteritems():
            for i, part in enumerate(zip(k, parts)):
                if part[0] != part[1]:
                    i -= 1
                    break
            if i < 0:
                continue
            i += 1
            common = tuple(k[:i])
            old = tuple(k[i:])
            new = tuple(parts[i:])
            break
        if old:
            self.branches.pop(k)
            t = Tree(self.valuetype)
            t.branches[old] = v
            self.branches[common] = t
        elif common:
            t = self.branches[common]
        if new:
            if common:
                return t.__get(new)
            t2 = t
            t = Tree(self.valuetype)
            t2.branches[new] = t
        if t.value is None:
            t.value = t.valuetype()
        return t.value

    indent = '  '

    def getContent(self, depth=0):
        '''
        Returns iterator of (depth, flag, key_or_value) tuples.
        If flag is 'value', key_or_value is a value object, otherwise
        (flag is 'key') it's a key string.
        '''
        keys = self.branches.keys()
        keys.sort()
        if self.value is not None:
            yield (depth, 'value', self.value)
        for key in keys:
            yield (depth, 'key', key)
            for child in self.branches[key].getContent(depth + 1):
                yield child

    def toJSON(self):
        '''
        Returns this Tree as a JSON-able tree of hashes.
        Only the values need to take care that they're JSON-able.
        '''
        if self.value is not None:
            return self.value
        return dict(('/'.join(key), self.branches[key].toJSON())
                    for key in self.branches.keys())

    def getStrRows(self):
        def tostr(t):
            if t[1] == 'key':
                return self.indent * t[0] + '/'.join(t[2])
            return self.indent * (t[0] + 1) + str(t[2])

        return map(tostr, self.getContent())

    def __str__(self):
        return '\n'.join(self.getStrRows())


class AddRemove(object):
    def __init__(self, key=None):
        self.left = self.right = None
        self.key = key

    def set_left(self, left):
        if not isinstance(left, set):
            left = set(l for l in left)
        self.left = left

    def set_right(self, right):
        if not isinstance(right, set):
            right = set(l for l in right)
        self.right = right

    def __iter__(self):
        for item in sorted(self.left | self.right, key=self.key):
            if item in self.left and item in self.right:
                yield ('equal', item)
            elif item in self.left:
                yield ('delete', item)
            else:
                yield ('add', item)


class Observer(object):

    def __init__(self, filter=None, file_stats=False):
        self.summary = defaultdict(lambda: defaultdict(int))
        self.details = Tree(list)
        self.filter = filter
        self.file_stats = None
        if file_stats:
            self.file_stats = defaultdict(lambda: defaultdict(dict))

    # support pickling
    def __getstate__(self):
        state = dict(summary=self._dictify(self.summary), details=self.details)
        if self.file_stats is not None:
            state['file_stats'] = self._dictify(self.file_stats)
        return state

    def __setstate__(self, state):
        self.summary = defaultdict(lambda: defaultdict(int))
        if 'summary' in state:
            for loc, stats in state['summary'].iteritems():
                self.summary[loc].update(stats)
        self.file_stats = None
        if 'file_stats' in state:
            self.file_stats = defaultdict(lambda: defaultdict(dict))
            for k, d in state['file_stats'].iteritems():
                self.file_stats[k].update(d)
        self.details = state['details']
        self.filter = None

    def _dictify(self, d):
        plaindict = {}
        for k, v in d.iteritems():
            plaindict[k] = dict(v)
        return plaindict

    def toJSON(self):
        # Don't export file stats, even if we collected them.
        # Those are not part of the data we use toJSON for.
        return {
            'summary': self._dictify(self.summary),
            'details': self.details.toJSON()
        }

    def updateStats(self, file, stats):
        # in multi-project scenarios, this file might not be ours,
        # check that.
        # Pass in a dummy entity key '' to avoid getting in to
        # generic file filters. If we have stats for those,
        # we want to aggregate the counts
        if (self.filter is not None and
                self.filter(file, entity='') == 'ignore'):
            return
        for category, value in stats.iteritems():
            self.summary[file.locale][category] += value
        if self.file_stats is None:
            return
        if 'missingInFiles' in stats:
            # keep track of how many strings are in a missing file
            # we got the {'missingFile': 'error'} from the notify pass
            self.details[file].append({'count': stats['missingInFiles']})
            # missingInFiles should just be "missing" in file stats
            self.file_stats[file.locale][file.localpath]['missing'] = \
                stats['missingInFiles']
            return  # there are no other stats for missing files
        self.file_stats[file.locale][file.localpath].update(stats)

    def notify(self, category, file, data):
        rv = 'error'
        if category in ['missingFile', 'obsoleteFile']:
            if self.filter is not None:
                rv = self.filter(file)
            if rv != "ignore":
                self.details[file].append({category: rv})
            return rv
        if category in ['missingEntity', 'obsoleteEntity']:
            if self.filter is not None:
                rv = self.filter(file, data)
            if rv == "ignore":
                return rv
            self.details[file].append({category: data})
            return rv
        if category in ('error', 'warning'):
            self.details[file].append({category: data})
            self.summary[file.locale][category + 's'] += 1
        return rv

    def toExhibit(self):
        items = []
        for locale in sorted(self.summary.iterkeys()):
            summary = self.summary[locale]
            if locale is not None:
                item = {'id': 'xxx/' + locale,
                        'label': locale,
                        'locale': locale}
            else:
                item = {'id': 'xxx',
                        'label': 'xxx',
                        'locale': 'xxx'}
            item['type'] = 'Build'
            total = sum([summary[k]
                         for k in ('changed', 'unchanged', 'report', 'missing',
                                   'missingInFiles')
                         if k in summary])
            total_w = sum([summary[k]
                           for k in ('changed_w', 'unchanged_w', 'missing_w')
                           if k in summary])
            rate = (('changed' in summary and summary['changed'] * 100) or
                    0) / total
            item.update((k, summary.get(k, 0))
                        for k in ('changed', 'unchanged'))
            item.update((k, summary[k])
                        for k in ('report', 'errors', 'warnings')
                        if k in summary)
            item['missing'] = summary.get('missing', 0) + \
                summary.get('missingInFiles', 0)
            item['completion'] = rate
            item['total'] = total
            item.update((k, summary.get(k, 0))
                        for k in ('changed_w', 'unchanged_w', 'missing_w'))
            item['total_w'] = total_w
            result = 'success'
            if item.get('warnings', 0):
                result = 'warning'
            if item.get('errors', 0) or item.get('missing', 0):
                result = 'failure'
            item['result'] = result
            items.append(item)
        data = {
            "properties": dict.fromkeys(
                ("completion", "errors", "warnings", "missing", "report",
                 "missing_w", "changed_w", "unchanged_w",
                 "unchanged", "changed", "obsolete"),
                {"valueType": "number"}),
            "types": {
                "Build": {"pluralLabel": "Builds"}
            }}
        data['items'] = items
        return dumps(data, indent=2)

    def serialize(self, type="text"):
        if type == "exhibit":
            return self.toExhibit()
        if type == "json":
            return dumps(self.toJSON())

        def tostr(t):
            if t[1] == 'key':
                return '  ' * t[0] + '/'.join(t[2])
            o = []
            indent = '  ' * (t[0] + 1)
            for item in t[2]:
                if 'error' in item:
                    o += [indent + 'ERROR: ' + item['error']]
                elif 'warning' in item:
                    o += [indent + 'WARNING: ' + item['warning']]
                elif 'missingEntity' in item:
                    o += [indent + '+' + item['missingEntity']]
                elif 'obsoleteEntity' in item:
                    o += [indent + '-' + item['obsoleteEntity']]
                elif 'missingFile' in item:
                    o.append(indent + '// add and localize this file')
                elif 'obsoleteFile' in item:
                    o.append(indent + '// remove this file')
            return '\n'.join(o)

        out = []
        for locale, summary in sorted(self.summary.iteritems()):
            if locale is not None:
                out.append(locale + ':')
            out += [k + ': ' + str(v) for k, v in sorted(summary.iteritems())]
            total = sum([summary[k]
                         for k in ['changed', 'unchanged', 'report', 'missing',
                                   'missingInFiles']
                         if k in summary])
            rate = 0
            if total:
                rate = (('changed' in summary and summary['changed'] * 100) or
                        0) / total
            out.append('%d%% of entries changed' % rate)
        return '\n'.join(map(tostr, self.details.getContent()) + out)

    def __str__(self):
        return 'observer'


class ContentComparer:
    keyRE = re.compile('[kK]ey')
    nl = re.compile('\n', re.M)

    def __init__(self, observers, stat_observers=None):
        '''Create a ContentComparer.
        observer is usually a instance of Observer. The return values
        of the notify method are used to control the handling of missing
        entities.
        '''
        self.observers = observers
        if stat_observers is None:
            stat_observers = []
        self.stat_observers = stat_observers

    def merge(self, ref_entities, ref_map, ref_file, l10n_file, merge_file,
              missing, skips, ctx, canMerge, encoding):
        outdir = mozpath.dirname(merge_file)
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
        if not canMerge:
            shutil.copyfile(ref_file.fullpath, merge_file)
            print "copied reference to " + merge_file
            return
        if skips:
            # skips come in ordered by key name, we need them in file order
            skips.sort(key=lambda s: s.span[0])
        trailing = (['\n'] +
                    [ref_entities[ref_map[key]].all for key in missing] +
                    [ref_entities[ref_map[skip.key]].all for skip in skips
                     if not isinstance(skip, parser.Junk)])
        if skips:
            # we need to skip a few errornous blocks in the input, copy by hand
            f = codecs.open(merge_file, 'wb', encoding)
            offset = 0
            for skip in skips:
                chunk = skip.span
                f.write(ctx.contents[offset:chunk[0]])
                offset = chunk[1]
            f.write(ctx.contents[offset:])
        else:
            shutil.copyfile(l10n_file.fullpath, merge_file)
            f = codecs.open(merge_file, 'ab', encoding)
        print "adding to " + merge_file

        def ensureNewline(s):
            if not s.endswith('\n'):
                return s + '\n'
            return s

        f.write(''.join(map(ensureNewline, trailing)))
        f.close()

    def notify(self, category, file, data):
        """Check observer for the found data, and if it's
        not to ignore, notify stat_observers.
        """
        rvs = set(
            observer.notify(category, file, data)
            for observer in self.observers
            )
        if all(rv == 'ignore' for rv in rvs):
            return 'ignore'
        rvs.discard('ignore')
        for obs in self.stat_observers:
            # non-filtering stat_observers, ignore results
            obs.notify(category, file, data)
        if 'error' in rvs:
            return 'error'
        assert len(rvs) == 1
        return rvs.pop()

    def updateStats(self, file, stats):
        """Check observer for the found data, and if it's
        not to ignore, notify stat_observers.
        """
        for observer in self.observers + self.stat_observers:
            observer.updateStats(file, stats)

    br = re.compile('<br\s*/?>', re.U)
    sgml = re.compile('</?\w+.*?>', re.U | re.M)

    def countWords(self, value):
        """Count the words in an English string.
        Replace a couple of xml markup to make that safer, too.
        """
        value = self.br.sub(u'\n', value)
        value = self.sgml.sub(u'', value)
        return len(value.split())

    def remove(self, obsolete):
        self.notify('obsoleteFile', obsolete, None)
        pass

    def compare(self, ref_file, l10n, merge_file, extra_tests=None):
        try:
            p = parser.getParser(ref_file.file)
        except UserWarning:
            # no comparison, XXX report?
            return
        try:
            p.readContents(ref_file.getContents())
        except Exception, e:
            self.notify('error', ref_file, str(e))
            return
        ref = p.parse()
        ref_list = ref[1].keys()
        ref_list.sort()
        try:
            p.readContents(l10n.getContents())
            l10n_entities, l10n_map = p.parse()
            l10n_ctx = p.ctx
        except Exception, e:
            self.notify('error', l10n, str(e))
            return

        l10n_list = l10n_map.keys()
        l10n_list.sort()
        ar = AddRemove()
        ar.set_left(ref_list)
        ar.set_right(l10n_list)
        report = missing = obsolete = changed = unchanged = keys = 0
        missing_w = changed_w = unchanged_w = 0  # word stats
        missings = []
        skips = []
        checker = getChecker(l10n, reference=ref[0], extra_tests=extra_tests)
        for action, entity in ar:
            if action == 'delete':
                # missing entity
                _rv = self.notify('missingEntity', l10n, entity)
                if _rv == "ignore":
                    continue
                if _rv == "error":
                    # only add to missing entities for l10n-merge on error,
                    # not report
                    missings.append(entity)
                    missing += 1
                    refent = ref[0][ref[1][entity]]
                    missing_w += self.countWords(refent.val)
                else:
                    # just report
                    report += 1
            elif action == 'add':
                # obsolete entity or junk
                if isinstance(l10n_entities[l10n_map[entity]],
                              parser.Junk):
                    junk = l10n_entities[l10n_map[entity]]
                    params = (junk.val,) + junk.position() + junk.position(-1)
                    self.notify('error', l10n,
                                'Unparsed content "%s" from line %d column %d'
                                ' to line %d column %d' % params)
                    if merge_file is not None:
                        skips.append(junk)
                elif self.notify('obsoleteEntity', l10n,
                                 entity) != 'ignore':
                    obsolete += 1
            else:
                # entity found in both ref and l10n, check for changed
                refent = ref[0][ref[1][entity]]
                l10nent = l10n_entities[l10n_map[entity]]
                if self.keyRE.search(entity):
                    keys += 1
                else:
                    if refent.val == l10nent.val:
                        self.doUnchanged(l10nent)
                        unchanged += 1
                        unchanged_w += self.countWords(refent.val)
                    else:
                        self.doChanged(ref_file, refent, l10nent)
                        changed += 1
                        changed_w += self.countWords(refent.val)
                        # run checks:
                if checker:
                    for tp, pos, msg, cat in checker.check(refent, l10nent):
                        # compute real src position, if first line,
                        # col needs adjustment
                        if isinstance(pos, tuple):
                            _l, col = l10nent.value_position()
                            # line, column
                            if pos[0] == 1:
                                col = col + pos[1]
                            else:
                                col = pos[1]
                                _l += pos[0] - 1
                        else:
                            _l, col = l10nent.value_position(pos)
                        # skip error entities when merging
                        if tp == 'error' and merge_file is not None:
                            skips.append(l10nent)
                        self.notify(tp, l10n,
                                    u"%s at line %d, column %d for %s" %
                                    (msg, _l, col, refent.key))
                pass
        if merge_file is not None and (missings or skips):
            self.merge(
                ref[0], ref[1], ref_file,
                l10n, merge_file, missings, skips, l10n_ctx,
                p.canMerge, p.encoding)
        stats = {}
        for cat, value in (
                ('missing', missing),
                ('missing_w', missing_w),
                ('report', report),
                ('obsolete', obsolete),
                ('changed', changed),
                ('changed_w', changed_w),
                ('unchanged', unchanged),
                ('unchanged_w', unchanged_w),
                ('keys', keys)):
            if value:
                stats[cat] = value
        self.updateStats(l10n, stats)
        pass

    def add(self, orig, missing):
        if self.notify('missingFile', missing, None) == "ignore":
            # filter said that we don't need this file, don't count it
            return
        f = orig
        try:
            p = parser.getParser(f.file)
        except UserWarning:
            return
        try:
            p.readContents(f.getContents())
            entities, map = p.parse()
        except Exception, e:
            self.notify('error', f, str(e))
            return
        self.updateStats(missing, {'missingInFiles': len(map)})
        missing_w = 0
        for e in entities:
            missing_w += self.countWords(e.val)
        self.updateStats(missing, {'missing_w': missing_w})

    def doUnchanged(self, entity):
        # overload this if needed
        pass

    def doChanged(self, file, ref_entity, l10n_entity):
        # overload this if needed
        pass


def compareProjects(project_configs, stat_observer=None,
                    file_stats=False,
                    merge_stage=None, clobber_merge=False):
    locales = set()
    observers = []
    for project in project_configs:
        observers.append(
            Observer(filter=project.filter, file_stats=file_stats))
        locales.update(project.locales)
    if stat_observer is not None:
        stat_observers = [stat_observer]
    else:
        stat_observers = None
    comparer = ContentComparer(observers, stat_observers=stat_observers)
    for locale in sorted(locales):
        files = paths.ProjectFiles(locale, project_configs,
                                   mergebase=merge_stage)
        root = mozpath.commonprefix([m['l10n'].prefix for m in files.matchers])
        if merge_stage is not None:
            if clobber_merge:
                mergematchers = set(_m.get('merge') for _m in files.matchers)
                mergematchers.discard(None)
                for matcher in mergematchers:
                    clobberdir = matcher.prefix
                    if os.path.exists(clobberdir):
                        shutil.rmtree(clobberdir)
                        print "clobbered " + clobberdir
        for l10npath, refpath, mergepath, extra_tests in files:
            # module and file path are needed for legacy filter.py support
            module = None
            fpath = mozpath.relpath(l10npath, root)
            for _m in files.matchers:
                if _m['l10n'].match(l10npath):
                    if _m['module']:
                        # legacy ini support, set module, and resolve
                        # local path against the matcher prefix,
                        # which includes the module
                        module = _m['module']
                        fpath = mozpath.relpath(l10npath, _m['l10n'].prefix)
                    break
            reffile = paths.File(refpath, fpath or refpath, module=module)
            l10n = paths.File(l10npath, fpath or l10npath,
                              module=module, locale=locale)
            if not os.path.exists(l10npath):
                comparer.add(reffile, l10n)
                continue
            if not os.path.exists(refpath):
                comparer.remove(l10n)
                continue
            comparer.compare(reffile, l10n, mergepath, extra_tests)
    return observers
