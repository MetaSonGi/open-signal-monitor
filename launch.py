"""One entry point; separate apps retain their own processes and data ownership."""
import argparse
import runpy

APPS = {
    'collector': ('operations_app', 'Equipment data collection'),
    'studio': ('learning.studio', 'Layout, mapping and manufacturing AI lessons'),
    'mes': ('learning.mes', 'Work orders and LOT management'),
    'pop': ('learning.pop', 'Shop-floor production reporting'),
    'web': ('collector_api', 'Read-only local dashboard on port 8808'),
}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', choices=APPS, nargs='?', default='collector')
    parser.add_argument('--list', action='store_true', help='Show apps without opening a window or DB')
    args = parser.parse_args(argv)
    if args.list:
        for key, (_, description) in APPS.items():
            print(f'{key}: {description}')
        return
    # Each module has its own __main__; do not pass launcher arguments to its parser.
    import sys
    previous = sys.argv
    try:
        sys.argv = [APPS[args.app][0]]
        runpy.run_module(APPS[args.app][0], run_name='__main__')
    finally:
        sys.argv = previous

if __name__ == '__main__':
    main()
