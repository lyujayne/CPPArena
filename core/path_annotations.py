"""Shared entry/exit annotations for live plots, exports and offline replay."""


def draw_partition(ax, polygon, fill_color=None):
    from matplotlib.patches import Polygon
    import matplotlib.patheffects as effects
    if fill_color:
        ax.add_patch(Polygon(polygon, closed=True, facecolor=fill_color, edgecolor='none', alpha=.08, zorder=2))
    outline = Polygon(polygon, closed=True, fill=False, edgecolor='#172554', linewidth=2.8, zorder=5,
                      joinstyle='round', capstyle='round')
    outline.set_path_effects([effects.Stroke(linewidth=4.4, foreground='white'), effects.Normal()])
    outline.set_gid('decomposition-boundary')
    ax.add_patch(outline)
    return outline


def draw_partitions(ax, polygons, fill_color=None):
    """Union shared edges before painting the halo so vertices remain continuous."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from matplotlib.collections import LineCollection
    from matplotlib.patches import Polygon as Patch
    import matplotlib.patheffects as effects
    polygons = [list(poly) for poly in polygons if len(poly) >= 3]
    if not polygons:
        return
    if fill_color:
        for poly in polygons:
            ax.add_patch(Patch(poly, facecolor=fill_color, edgecolor='none', alpha=.05, zorder=2))
    merged = unary_union([Polygon(poly).boundary for poly in polygons])
    lines = [merged] if merged.geom_type == 'LineString' else list(merged.geoms)
    collection = LineCollection([list(line.coords) for line in lines], colors='#172554',
        linewidths=2.8, zorder=5, capstyle='round', joinstyle='round')
    collection.set_path_effects([effects.Stroke(linewidth=4.4, foreground='white'), effects.Normal()])
    collection.set_gid('decomposition-boundary')
    ax.add_collection(collection)
    return collection


def _direction_arrows(ax, segments, color, budget=60):
    segments = [(a, b) for a, b in segments if sum((x-y)**2 for x, y in zip(a, b)) > 1e-12]
    stride = max(1, (len(segments)+budget-1)//budget)
    for a, b in segments[::stride]:
        start = tuple(x+.36*(y-x) for x, y in zip(a, b))
        end = tuple(x+.64*(y-x) for x, y in zip(a, b))
        artist = ax.annotate('', xy=end, xytext=start, zorder=10,
            arrowprops=dict(arrowstyle='-|>', mutation_scale=8, color=color, lw=.8,
                            shrinkA=0, shrinkB=0), annotation_clip=True)
        artist.set_gid('route-direction')


def draw_route(ax, run, color, label=None, show_internal=True, show_transfers=True):
    import matplotlib.patheffects as effects
    paths = run.get('internal_paths') or []
    waypoints = run.get('waypoints') or []
    labeled = False
    if not paths:
        if waypoints and show_internal:
            ax.plot([p[0] for p in waypoints], [p[1] for p in waypoints], '-', color=color, lw=1, label=label)
        return
    if show_internal:
        for path in paths:
            if len(path) >= 2:
                line, = ax.plot([p[0] for p in path], [p[1] for p in path], '-', color=color,
                        lw=1.25, zorder=8, solid_capstyle='round', solid_joinstyle='round',
                        label=label if not labeled else None)
                line.set_path_effects([effects.Stroke(linewidth=2, foreground='white'), effects.Normal()])
                _direction_arrows(ax, list(zip(path, path[1:])), color, max(6, 100//len(paths)))
                labeled = True
    if show_transfers and waypoints:
        position = waypoints[0]
        segments = []
        for path in paths:
            if path:
                segments.append((position, path[0]))
                position = path[-1]
        segments.append((position, waypoints[-1]))
        for a, b in segments:
            if sum((x-y)**2 for x, y in zip(a, b)) > 1e-14:
                ax.plot([a[0], b[0]], [a[1], b[1]], '--', color=color, alpha=.8,
                        lw=1.3, zorder=8, dash_capstyle='round', label=label if not labeled else None)
                labeled = True
        _direction_arrows(ax, segments, color, 25)


def subregion_endpoints(run):
    paths = run.get('internal_paths', [])
    for index, item in enumerate(run.get('subregion_sequence', [])):
        path = paths[index] if index < len(paths) else []
        entry = item.get('entry') or (path[0] if path else None)
        exit = item.get('exit') or (path[-1] if path else None)
        if entry is not None and exit is not None:
            yield dict(order=item.get('order', index+1), entry=entry, exit=exit,
                       region_id=item.get('region_id'), subregion_id=item.get('subregion_id'))


def draw_entry_exit(ax, run):
    artists = []
    for item in subregion_endpoints(run):
        order = item['order']
        for key, prefix, color, marker, offset in (
            ('entry', '入', '#087f5b', 'o', (7, 10)),
            ('exit', '出', '#c2410c', 's', (7, -15))):
            x, y = item[key]
            mark = ax.scatter([x], [y], marker=marker, s=40, c=color,
                              edgecolors='white', linewidths=.8, zorder=11)
            mark.set_gid(f'{key}-{order}')
            text = ax.annotate(f'{prefix}{order}', (x, y), xytext=offset,
                textcoords='offset points', color=color, fontsize=8, zorder=12,
                bbox=dict(boxstyle='round,pad=.15', fc='white', ec=color, alpha=.9))
            text.set_gid(f'{key}-label-{order}')
            artists.extend((mark, text))
    return artists
