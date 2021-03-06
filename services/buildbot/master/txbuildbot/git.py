from twisted.python import log
from twisted.internet import defer

from buildbot.process import buildstep
from buildbot.steps.source import Source
from buildbot.steps.source.git import Git
from buildbot.status.results import SUCCESS


def mungeBranch(branch):
    """
    Remove the leading prefix, that comes from svn branches.
    """
    if not branch:
        return 'trunk'

    for cutoff in ['/branches/', 'branches/', '/']:
        if branch.startswith(cutoff):
            branch = branch[len(cutoff):]
            break
    return branch


def isTrunk(branch):
    """
    Is the branch trunk?
    """
    return mungeBranch(branch) == 'trunk'


def isRelease(branch):
    """
    Is the branch a release branch?
    """
    return mungeBranch(branch).startswith('release-')


def isSafeBranch(branch):
    """
    Is this branch a safe branch? That is, is it on a real branch?
    """
    return not mungeBranch(branch).startswith('refs/pull')


class MergeForward(Source):
    """
    Merge with trunk.
    """
    name = 'merge-forward'
    description = ['merging', 'forward']
    descriptionDone = ['merge', 'forward']
    haltOnFailure = True


    def __init__(self, repourl, branch='trunk', **kwargs):
        self.repourl = repourl
        self.branch = branch
        kwargs['env'] = {
                'GIT_AUTHOR_EMAIL': 'buildbot@twistedmatrix.com',
                'GIT_AUTHOR_NAME': 'Twisted Buildbot',
                'GIT_COMMITTER_EMAIL': 'buildbot@twistedmatrix.com',
                'GIT_COMMITTER_NAME': 'Twisted Buildbot',
                }
        Source.__init__(self, **kwargs)
        self.addFactoryArguments(repourl=repourl, branch=branch)


    def startVC(self, branch, revision, patch):

        if not isSafeBranch(branch):
            raise ValueError("No building on pull requests.")

        self.stdio_log = self.addLog('stdio')

        self.step_status.setText(['merging', 'forward'])
        d = defer.succeed(None)
        if not isTrunk(branch):
            d.addCallback(lambda _: self._fetch())
        if not (isTrunk(branch) or isRelease(branch)):
            d.addCallback(lambda _: self._merge())
        if isTrunk(branch):
            d.addCallback(lambda _: self._getPreviousVersion())
        else:
            d.addCallback(lambda _: self._getMergeBase())
        d.addCallback(self._setLintVersion)

        d.addCallback(lambda _: SUCCESS)
        d.addCallbacks(self.finished, self.checkDisconnect)
        d.addErrback(self.failed)


    def finished(self, results):
        if results == SUCCESS:
            self.step_status.setText(['merge', 'forward'])
        else:
            self.step_status.setText(['merge', 'forward', 'failed'])
        return Source.finished(self, results)


    def _fetch(self):
        d = self._dovccmd(['remote', 'set-url', 'origin', self.repourl])
        d.addCallback(lambda _: self._dovccmd(['fetch', 'origin']))
        return d


    def _merge(self):
        return self._dovccmd(['merge',
                              '--no-ff', '--no-stat',
                              'origin/trunk'])


    def _getPreviousVersion(self):
        return self._dovccmd(['rev-parse', 'HEAD~1'],
                              collectStdout=True)


    def _getMergeBase(self):
        return self._dovccmd(['merge-base', 'HEAD', 'origin/trunk'],
                              collectStdout=True)


    def _setLintVersion(self, version):
        self.setProperty("lint_revision", version.strip(), "merge-forward")


    def _dovccmd(self, command, abandonOnFailure=True, collectStdout=False, extra_args={}):
        cmd = buildstep.RemoteShellCommand(self.workdir, ['git'] + command,
                                           env=self.env,
                                           logEnviron=self.logEnviron,
                                           collectStdout=collectStdout,
                                           **extra_args)
        cmd.useLog(self.stdio_log, False)
        d = self.runCommand(cmd)
        def evaluateCommand(cmd):
            if abandonOnFailure and cmd.rc != 0:
                log.msg("Source step failed while running command %s" % cmd)
                raise buildstep.BuildStepFailed()
            if collectStdout:
                return cmd.stdout
            else:
                return cmd.rc
        d.addCallback(lambda _: evaluateCommand(cmd))
        return d


class TwistedGit(Git):
    """
    Temporary support for the transitionary stage between SVN and Git.
    """

    def startVC(self, branch, revision, patch):
        if not isSafeBranch(branch):
            raise ValueError("No building on pull requests.")

        return Git.startVC(self, branch, revision, patch)
