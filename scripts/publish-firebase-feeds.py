"""Publish only the two reviewed feeds, preserving every other live Hosting file."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
API = 'https://firebasehosting.googleapis.com/v1beta1/'
SITE = 'paran-5dcac'
TARGETS = {
    '/benefit/data/feed.json': 'data/feed.json',
    '/benefit/data/learning-feed.json': 'data/learning-feed.json',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def version_path(name):
    parts = name.strip('/').split('/')
    if len(parts) < 4 or parts[-4:-1] != ['sites', SITE, 'versions']:
        raise ValueError('Unexpected Hosting version site')
    return '/'.join(parts[-4:])


def validate_inventory(before, after, targets):
    if set(targets) != set(TARGETS):
        raise ValueError('Unexpected target paths; only two feeds may be published')
    if set(after) != set(before) | set(targets):
        raise ValueError('Unrelated live files would be added or deleted')
    for name, expected in before.items():
        if name not in targets and after.get(name) != expected:
            raise ValueError('Unrelated live content changed')
    for name, expected in targets.items():
        if after.get(name) != expected:
            raise ValueError('Published feed bytes differ')


def verify_public_feeds(original, version, opener=None, sleep=None):
    """Retry only public reads while the confirmed release reaches CDN edges."""
    opener = opener or urllib.request.urlopen
    sleep = sleep or time.sleep
    version_id = version_path(version).split('/')[-1]
    delays = (0, 1, 2, 4, 8)
    for target, expected in original.items():
        if target not in TARGETS:
            raise ValueError('Unexpected public verification path')
        last_error = 'No response'
        for attempt, delay in enumerate(delays):
            if delay:
                sleep(delay)
            # Query strings are part of the Hosting CDN cache key. Each read
            # must avoid caching a temporarily stale post-release response.
            query = urllib.parse.urlencode({
                'hosting_version': version_id,
                'verify': f'{time.time_ns()}-{attempt}',
            })
            request = urllib.request.Request(
                'https://paran-5dcac.web.app' + target + '?' + query,
                headers={'Cache-Control': 'no-cache'},
            )
            try:
                with opener(request, timeout=15) as response:
                    actual = response.read(len(expected) + 1)
                    if response.status == 200 and actual == expected:
                        break
                    last_error = f'HTTP {response.status}, received SHA256 {digest(actual)}'
            except urllib.error.HTTPError as error:
                last_error = f'HTTP {error.code}'
                if error.code not in (408, 429) and error.code < 500:
                    raise RuntimeError(
                        f'Public Firebase feed verification rejected for {target}: {last_error}'
                    ) from None
            except (urllib.error.URLError, TimeoutError) as error:
                last_error = type(error).__name__
        else:
            raise ValueError(
                f'Public Firebase feed verification failed for {target} at version {version_id} '
                f'after {len(delays)} read attempts ({last_error}); do not repeat the release'
            )


class Hosting:
    def __init__(self, token):
        if not token:
            raise ValueError('A short-lived access token is required')
        self.token = token

    def request(self, method, resource, payload=None, upload=False):
        url = resource if resource.startswith('https://') else API + resource.lstrip('/')
        host = urllib.parse.urlparse(url).hostname
        if host not in ('firebasehosting.googleapis.com', 'upload-firebasehosting.googleapis.com'):
            raise ValueError('Unexpected authenticated API destination')
        data = payload if upload else None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': 'Bearer ' + self.token,
            'Content-Type': 'application/octet-stream' if upload else 'application/json',
            'User-Agent': 'BenefitReviewedFeedPublisher/1.0',
        })
        # Never automatically repeat a write with an unknown outcome.
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read(12000000)
                return {} if upload or not body else json.loads(body)
        except urllib.error.HTTPError as error:
            try:
                message = json.loads(error.read(20000)).get('error', {}).get('message', 'API rejected request')
            except (ValueError, AttributeError):
                message = 'API rejected request'
            raise RuntimeError(f'Hosting {method} HTTP {error.code}: {message[:1500]}') from None

    def live(self):
        return self.request('GET', f'sites/{SITE}/channels/live')['release']['version']

    def files(self, version):
        result = {}
        page = None
        while True:
            query = {'pageSize': 1000}
            if page:
                query['pageToken'] = page
            data = self.request('GET', version_path(version) + '/files?' + urllib.parse.urlencode(query))
            for item in data.get('files', []):
                name = '/' + item['path'].lstrip('/')
                if name in result or not item.get('hash'):
                    raise ValueError('Incomplete live file identity')
                result[name] = item['hash']
            page = data.get('nextPageToken')
            if not page:
                return result

    def clone(self, baseline):
        operation = self.request('POST', f'sites/{SITE}/versions:clone', {
            'sourceVersion': version_path(baseline['name']), 'finalize': False,
        })
        for _ in range(100):
            result = self.request('GET', operation['name'])
            if result.get('done'):
                if result.get('error'):
                    raise ValueError('Hosting clone failed; inspect the operation before retrying')
                return result['response']
            time.sleep(1.5)
        raise ValueError('Hosting clone still pending; do not repeat the release')


def publish(client, dry_run=False):
    original = {}
    compressed = {}
    for target, relative in TARGETS.items():
        raw = (ROOT / relative).read_bytes()
        data = json.loads(raw)
        if not isinstance(data.get('notices'), list) or not data.get('generatedAt'):
            raise ValueError('Invalid reviewed public feed')
        if any(marker in raw.lower() for marker in (b'siuhwang', b'github.com', b'github.io')):
            raise ValueError('Personal repository reference in public feed')
        original[target] = raw
        compressed[target] = gzip.compress(raw, compresslevel=9, mtime=0)
    target_hashes = {name: digest(body) for name, body in compressed.items()}
    baseline = client.live()
    if baseline.get('status') != 'FINALIZED':
        raise ValueError('No finalized live baseline')
    before = client.files(baseline['name'])
    if len(before) != int(baseline['fileCount']):
        raise ValueError('Incomplete live inventory')
    summary = {'baseline': baseline['name'], 'targetCount': 2, 'liveFilesPreserved': len(before) - 2}
    if dry_run:
        return dict(summary, mode='dry-run', released=False)
    if all(before.get(name) == sha for name, sha in target_hashes.items()):
        verify_public_feeds(original, baseline['name'])
        return dict(summary, mode='already-current', released=False, version=baseline['name'],
                    configPreserved=True, publicBytesVerified=True)
    clone = client.clone(baseline)
    if clone.get('config', {}) != baseline.get('config', {}):
        raise ValueError('Cloned Hosting configuration differs')
    populated = client.request('POST', clone['name'] + ':populateFiles', {'files': target_hashes})
    by_hash = {digest(body): body for body in compressed.values()}
    for sha in populated.get('uploadRequiredHashes', []):
        if sha not in by_hash:
            raise ValueError('Upload requested an unrelated file hash')
        client.request('POST', populated['uploadUrl'].rstrip('/') + '/' + sha, by_hash[sha], upload=True)
    finalized = client.request('PATCH', clone['name'] + '?updateMask=status', {'status': 'FINALIZED'})
    if finalized.get('config', {}) != baseline.get('config', {}):
        raise ValueError('Final Hosting configuration differs')
    after = client.files(clone['name'])
    validate_inventory(before, after, target_hashes)
    if client.live()['name'].split('/')[-1] != baseline['name'].split('/')[-1]:
        raise ValueError('Another deployment changed live; this prepared version was not released')
    release = client.request('POST', f'sites/{SITE}/channels/live/releases?' +
                             urllib.parse.urlencode({'versionName': clone['name']}), {
                                 'message': 'Refresh two reviewed public benefit feeds; preserve all other live Hosting files',
                             })
    if client.live()['name'].split('/')[-1] != clone['name'].split('/')[-1]:
        raise ValueError('Release outcome not confirmed; inspect before retrying')
    verify_public_feeds(original, clone['name'])
    return dict(summary, mode='publish', released=True, version=clone['name'], release=release['name'],
                configPreserved=True, publicBytesVerified=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    options = parser.parse_args()
    result = publish(Hosting(os.environ.get('FIREBASE_ACCESS_TOKEN')), dry_run=options.dry_run)
    print(json.dumps(result))
