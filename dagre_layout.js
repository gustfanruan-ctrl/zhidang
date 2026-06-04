// dagre-layout.js — reads graph JSON from stdin, outputs positioned JSON
const dagre = require('@dagrejs/dagre');

let input = '';
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
    try {
        const data = JSON.parse(input);
        const g = new dagre.graphlib.Graph({ compound: true, directed: true });
        g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 60, marginx: 20, marginy: 20 });
        g.setDefaultEdgeLabel(() => ({}));

        const nodeMap = {};
        for (const n of data.nodes) {
            nodeMap[n.id] = n;
            g.setNode(n.id, { width: n.width || 160, height: n.height || 60 });
        }

        // Compound nesting
        for (const n of data.nodes) {
            if (n.parent_dept_id && nodeMap[n.parent_dept_id]) {
                try { g.setParent(n.id, n.parent_dept_id); } catch(e) {}
            }
        }

        // Edges
        for (const e of data.edges) {
            const src = nodeMap[e.source];
            const tgt = nodeMap[e.target];
            if (!src || !tgt) continue;
            // Skip parent-child edges that would create cycles
            if (src.parent_dept_id === e.target || tgt.parent_dept_id === e.source) continue;
            if (src.node_type === 'dept' && tgt.node_type === 'user' && tgt.parent_dept_id === e.source) continue;
            try { g.setEdge(e.source, e.target); } catch(e) {}
        }

        dagre.layout(g);

        // Build output
        const result = { nodes: [], edges: data.edges || [], width: 0, height: 0 };
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

        for (const nid of g.nodes()) {
            const node = g.node(nid);
            const orig = nodeMap[nid] || {};
            const x = node.x - node.width / 2;
            const y = node.y - node.height / 2;
            const w = node.width;
            const h = node.height;
            if (x < minX) minX = x;
            if (y < minY) minY = y;
            if (x + w > maxX) maxX = x + w;
            if (y + h > maxY) maxY = y + h;
            result.nodes.push({
                id: nid,
                name: orig.name || '',
                node_type: orig.node_type || 'user',
                position: orig.position || '',
                tagA: orig.tagA || '',
                node_manager: orig.node_manager || '0',
                parent_dept_id: orig.parent_dept_id || '',
                x: Math.round(x),
                y: Math.round(y),
                width: Math.round(w),
                height: Math.round(h),
            });
        }

        result.width = Math.round(maxX - minX + 80);
        result.height = Math.round(maxY - minY + 80);
        result.offsetX = Math.round(-minX + 40);
        result.offsetY = Math.round(-minY + 40);

        process.stdout.write(JSON.stringify(result));
    } catch(e) {
        process.stderr.write('ERROR: ' + e.message + '\n' + e.stack + '\n');
        process.exit(1);
    }
});
