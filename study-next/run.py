"""Executable offline lifecycle for the new instrument; no live clients loaded.

Research plan/validation are supported, but live execution is deliberately closed
until a fresh prospective preflight evidence contract is implemented. The frozen
v002 live entry point is retained unchanged for provenance, not a new allowance.
"""
import argparse
import os
from pathlib import Path
import sys

import bootstrap
from adapters import canonical, strict_json
from budget import CampaignBudget
from coordinator import make_plan, run_phase
from durability import _lock, _unlock
from locks import write_once
import definition_next


class OperationLock:
    """Serialize lifecycle mutations before an experiment directory exists."""
    def __init__(self, experiment):
        path = Path(experiment).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = (path.parent / ('.' + path.name + '.operation.lock')).open('a+b')
        self.locked = False
        try:
            _lock(self.file)
            self.locked = True
        except BaseException:
            self.file.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            if self.locked:
                _unlock(self.file)
        finally:
            self.file.close()


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest='command', required=True)
    fixture = commands.add_parser('fixture', help='create clearly simulated, fresh instrument inputs')
    fixture.add_argument('--output', type=Path, required=True)
    freeze = commands.add_parser('freeze')
    freeze.add_argument('--experiment', type=Path, required=True)
    freeze.add_argument('--dataset', type=Path, required=True)
    freeze.add_argument('--settings', type=Path, required=True)
    for name in ('plan', 'validate', 'run', 'report', 'freeze-thresholds'):
        command = commands.add_parser(name)
        command.add_argument('--experiment', type=Path, required=True)
        if name in ('plan', 'run', 'report'):
            command.add_argument('--phase', choices=definition_next.PHASES, required=True)
        if name == 'run':
            command.add_argument('--execute', action='store_true', help='actually execute the selected simulated phase')
            command.add_argument('--simulate', action='store_true', help='use labeled fake responses, never inference')
            command.add_argument('--approval-reference')
            command.add_argument('--resume', action='store_true')
            command.add_argument('--reconcile-reference')
            command.add_argument('--stop-after', type=int)
        if name == 'report':
            command.add_argument('--tokenizer-environment', type=Path)
            command.add_argument('--output', type=Path)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == 'fixture':
        # A deliberately separate ledger for simulated tests is never a real
        # campaign reset. This command has no network transport or live mode.
        from fixtures_next import settings, write_dataset
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=False)
        dataset = write_dataset(output / 'dataset')
        campaign_path = output / 'SIMULATED-campaign.jsonl'
        with CampaignBudget(campaign_path, '2', create=True):
            pass
        write_once(output / 'settings.json', settings(campaign_path))
        result = {'evidence': 'simulated instrument only', 'dataset': str(dataset),
                  'settings': str(output / 'settings.json'), 'campaign': str(campaign_path)}
    elif args.command == 'freeze':
        with OperationLock(args.experiment):
            result = definition_next.freeze(args.experiment, args.dataset,
                strict_json(args.settings.read_text(encoding='utf8')))
        result = {'version': 3, 'frozen': str(args.experiment.resolve()),
                  'purpose': result['settings']['purpose']}
    elif args.command == 'validate':
        frozen = definition_next.verify(args.experiment)
        result = {'valid': True, 'version': 3, 'purpose': frozen['settings']['purpose']}
    elif args.command == 'plan' or (args.command == 'run' and not args.execute):
        result = {'execution': False, 'plan': make_plan(args.experiment, args.phase)}
    elif args.command == 'freeze-thresholds':
        with OperationLock(args.experiment):
            result = definition_next.freeze_thresholds(args.experiment)
    elif args.command == 'report':
        with OperationLock(args.experiment):
            result = definition_next.report(args.experiment, args.phase, args.tokenizer_environment)
            if args.output is not None:
                output = args.output.resolve()
                if output.is_relative_to(bootstrap.SOURCE_ROOT):
                    raise ValueError('generated report must be outside source checkout')
                definition_next._write_checked(output, result)
    elif args.command == 'run':
        if not args.approval_reference or not args.approval_reference.strip():
            raise PermissionError('execution requires an explicit approval reference')
        with OperationLock(args.experiment):
            frozen = definition_next.verify(args.experiment)
            settings = frozen['settings']
            if not args.simulate or settings['purpose'] != 'instrument-test':
                raise PermissionError('this new CLI executes instrument-test simulation only; '
                                      'fresh research needs verified preflight evidence before live wiring')
            from fixtures_next import FakeProviders
            cases, _, models = definition_next.phase_inputs(args.experiment, args.phase)
            fake = FakeProviders(cases, models=settings['models'])
            with CampaignBudget(settings['campaign_path'], settings['cloud_cap_usd']) as campaign:
                result = run_phase(args.experiment, args.phase, fake.transports(tuple(models)), campaign,
                    approved=True, resume=args.resume, reconcile_reference=args.reconcile_reference,
                    stop_after=args.stop_after)
            result = {'evidence': 'simulated instrument only', 'fake_dispatches_this_invocation': len(fake.calls),
                      'approval_reference': args.approval_reference, 'summary': result}
    else:
        raise ValueError('unrecognized command')
    print(canonical(result))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        raise SystemExit(2)
