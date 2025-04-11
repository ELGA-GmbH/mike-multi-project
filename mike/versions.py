import json
import re
from verspec.loose import LooseVersion as Version

from . import jsonpath


def _ensure_version(version):
    if not isinstance(version, Version):
        return Version(version)
    return version


class VersionInfo:
    def __init__(self, version, title=None, aliases=[], properties=None):
        self._check_version(str(version), 'version')
        for i in aliases:
            self._check_version(i, 'alias')

        version_name = str(version)
        self.version = _ensure_version(version)
        self.title = version_name if title is None else title
        self.aliases = set(aliases)
        self.properties = properties

        if str(self.version) in self.aliases:
            raise ValueError('duplicated version and alias')

    
    @classmethod
    def from_json(cls, data):
        return cls(
            data['version'],
            data['title'],
            data['aliases'],
            data.get('properties')
        )

    def to_json(self):
        data = {
            'version': str(self.version),
            'title': self.title,
            'aliases': list(self.aliases)
        }
        if self.properties:
            data['properties'] = self.properties
        return data


    @classmethod
    def loads(cls, data):
        return cls.from_json(json.loads(data))

    def dumps(self):
        return json.dumps(self.to_json(), indent=2)

    @staticmethod
    def _check_version(version, kind):
        if ( not version or version in ['.', '..'] or
             re.search(r'[\\/]', version) ):
            raise ValueError('{!r} is not a valid {}'.format(version, kind))

    def __eq__(self, rhs):
        return (str(self.version) == str(rhs.version) and
                self.title == rhs.title and
                self.aliases == rhs.aliases and
                self.properties == rhs.properties)

    def __repr__(self):
        return '<VersionInfo({!r}, {!r}, {{{}}}{})>'.format(
            self.version, self.title, ', '.join(repr(i) for i in self.aliases),
            ', {!r}'.format(self.properties) if self.properties else ''
        )

    def update(self, title=None, aliases=[]):
        for i in aliases:
            self._check_version(i, 'alias')
        if title is not None:
            self.title = title

        aliases = set(aliases)
        if str(self.version) in aliases:
            raise ValueError('duplicated version and alias')

        added = aliases - self.aliases
        self.aliases |= aliases
        return added

    def get_property(self, expr, **kwargs):
        return jsonpath.get_value(self.properties, expr, **kwargs)

    def set_property(self, expr, value):
        self.properties = jsonpath.set_value(self.properties, expr, value)


class Versions:
    def __init__(self):
        self._data = {}  # Structure: { "component1": { "1.0": VersionInfo, "dev": VersionInfo }, ... }

    @classmethod
    def from_json(cls, data):
        result = cls()
        for component, versions in data.items():
            if component not in result._data:
                result._data[component] = {}

            for version_data in versions:
                version = VersionInfo.from_json(version_data)
                version_str = str(version.version)
                result._ensure_unique_aliases(component, version_str, version.aliases)
                result._data[component][version_str] = version
                
        return result

    def to_json(self):
        return [i.to_json() for i in iter(self)]

    @classmethod
    def loads(cls, data):
        return cls.from_json(json.loads(data))

    def dumps(self):
        return json.dumps(self.to_json(), indent=2)

    def __iter__(self):
        def key(info):
            # Development versions (i.e. those without a leading digit) should
            # be treated as newer than release versions.
            return (0 if re.match(r'v?\d', str(info.version))
                    else 1, info.version)

        return (i for i in sorted(self._data.values(), reverse=True, key=key))

    def __len__(self):
        return len(self._data)

    def __getitem__(self, k):
        return self._data[str(k)]

    def find(self, identifier, strict=False):
        identifier = str(identifier)
        if identifier in self._data:
            return (identifier,)
        for k, v in self._data.items():
            if identifier in v.aliases:
                return (k, identifier)
        if strict:
            raise KeyError(identifier)
        return None

    def _ensure_unique_aliases(self, component, version, aliases, update_aliases=False):
        removed_aliases = []

        # Check if `version` is already defined as an alias within the component
        key = self.find(component, version)
        if key and len(key) == 2:
            if not update_aliases:
                raise ValueError(f"Version '{version}' already exists in component '{component}'")
            removed_aliases.append(key)

        # Check if any `aliases` are already in use within the same component
        for alias in aliases:
            key = self.find(component, alias)
            if key and key[0] != version:
                if len(key) == 1:
                    raise ValueError(f"Alias '{alias}' is already specified as a version in component '{component}'")
                if not update_aliases:
                    raise ValueError(f"Alias '{alias}' already exists for version '{key[0]}' in component '{component}'")
                removed_aliases.append(key)

        return removed_aliases


    def add(self, component, version, title=None, aliases=[], update_aliases=False):
        v = str(version)

        # Ensure the component exists
        if component not in self._data:
            self._data[component] = {}

        # Ensure alias uniqueness within the given component
        removed_aliases = self._ensure_unique_aliases(component, v, aliases, update_aliases)

        print(f"Component '{component}' versions: {self._data[component]}")
        print(f"Checking if version '{v}' exists in the component...")

        # If the version already exists, update its title and aliases
        if v in self._data[component]:
            self._data[component][v].update(title, aliases)
        else:
            self._data[component][v] = VersionInfo(version, title, aliases)

        # Remove aliases from old versions within the same component
        for i in removed_aliases:
            self._data[component][i[0]].aliases.remove(i[1])

        return self._data[component][v]


    def update(self, component, identifier, title=None, aliases=[], update_aliases=False):
        key = self.find(component, identifier, strict=True)

        if not key:
            raise ValueError(f"Version '{identifier}' not found in component '{component}'")

        removed_aliases = self._ensure_unique_aliases(component, key[0], aliases, update_aliases)

        # Remove aliases from old versions within the same component
        for i in removed_aliases:
            self._data[component][i[0]].aliases.remove(i[1])

        return self._data[component][key[0]].update(title, aliases)


    def _remove_by_key(self, key):
        if len(key) == 1:
            item = self._data[key[0]]
            del self._data[key[0]]
        else:
            item = key[1]
            self._data[key[0]].aliases.remove(key[1])
        return item

    def remove(self, component, identifier):
        key = self.find(component, identifier, strict=True)

        if not key:
            raise ValueError(f"Version '{identifier}' not found in component '{component}'")

        return self._remove_by_key(component, key)


    def difference_update(self, component, identifiers):
        keys = [self.find(component, i, strict=True) for i in identifiers]

        if any(k is None for k in keys):
            missing_versions = [i for i, k in zip(identifiers, keys) if k is None]
            raise ValueError(f"Versions {missing_versions} not found in component '{component}'")

        return [self._remove_by_key(component, k) for k in keys]

