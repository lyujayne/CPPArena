"""Camera footprint evaluation from chosen scan segments, independent of solvers."""
import math


def scan_footprints(segments, width, height):
    from shapely.geometry import Polygon
    footprints = []
    for a, b in segments:
        length = math.dist(a, b)
        if length < 1e-10:
            continue
        dx, dy = ((b[0]-a[0])/length, (b[1]-a[1])/length)
        ux, uy = -dy*width/2, dx*width/2
        start = (a[0]-dx*height/2, a[1]-dy*height/2)
        end = (b[0]+dx*height/2, b[1]+dy*height/2)
        footprints.append(Polygon([(start[0]+ux, start[1]+uy), (end[0]+ux, end[1]+uy),
                                   (end[0]-ux, end[1]-uy), (start[0]-ux, start[1]-uy)]))
    return footprints


def evaluate_coverage(regions, segments, width, height):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    target = unary_union([Polygon(r.vertices) for r in regions])
    covered = unary_union(scan_footprints(segments, width, height))
    missed = target.difference(covered).area
    return {'covered_ratio': max(0., min(1., 1-missed/target.area)),
            'uncovered_area_m2': missed,
            'evaluation': 'union of chosen scan footprints intersected with union of original target regions'}
