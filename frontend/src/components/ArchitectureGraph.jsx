import React, { useState, useEffect } from 'react';
import { API_BASE } from '../config';

export default function ArchitectureGraph({ activeRepo }) {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [selectedNode, setSelectedNode] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    if (!activeRepo) return;
    fetchGraph();
  }, [activeRepo]);

  const fetchGraph = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/graph?path=${encodeURIComponent(activeRepo)}`);
      if (res.ok) {
        const data = await res.json();
        setGraphData(data);
        if (data.nodes && data.nodes.length > 0) {
          setSelectedNode(data.nodes[0]);
        }
      }
    } catch (e) {
      console.error('Failed to load architecture graph:', e);
    } finally {
      setLoading(false);
    }
  };

  const filteredNodes = filter === 'all'
    ? graphData.nodes
    : graphData.nodes.filter(n => n.type === filter);

  const outgoingLinks = selectedNode
    ? graphData.links.filter(l => l.source === selectedNode.id)
    : [];
  const incomingLinks = selectedNode
    ? graphData.links.filter(l => l.target === selectedNode.id)
    : [];

  return (
    <div className="card" style={{ maxWidth: '1180px', margin: '0 auto 24px auto', padding: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '10px' }}>
        <div>
          <span style={{ fontSize: '15px', fontWeight: '600' }}>Module Dependencies</span>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
            Cross-file import relationships extracted from the codebase AST.
          </p>
        </div>

        {/* Filter buttons */}
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          {['all', 'code', 'config', 'doc'].map(cat => (
            <button
              key={cat}
              onClick={() => setFilter(cat)}
              className="btn btn-secondary"
              style={{
                fontSize: '11.5px',
                padding: '3px 8px',
                textTransform: 'capitalize',
                backgroundColor: filter === cat ? '#27272a' : '#18181b',
                color: filter === cat ? '#f4f4f5' : 'var(--text-secondary)'
              }}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
          Loading dependencies...
        </div>
      ) : graphData.nodes.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
          No dependencies found yet. Analyze a codebase to inspect module relations.
        </div>
      ) : (
        <div className="grid-dependencies">
          {/* File List Grid */}
          <div style={{
            backgroundColor: '#18181b',
            borderRadius: '6px',
            border: '1px solid var(--border-color)',
            padding: '10px',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
            gap: '8px',
            alignContent: 'start',
            maxHeight: '380px',
            overflowY: 'auto'
          }}>
            {filteredNodes.map(node => {
              const isSelected = selectedNode?.id === node.id;
              return (
                <div
                  key={node.id}
                  onClick={() => setSelectedNode(node)}
                  style={{
                    backgroundColor: isSelected ? '#27272a' : '#121215',
                    border: `1px solid ${isSelected ? '#52525b' : 'var(--border-color)'}`,
                    borderRadius: '5px',
                    padding: '8px 10px',
                    cursor: 'pointer'
                  }}
                >
                  <div style={{ fontSize: '10.5px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '600' }}>
                    {node.type}
                  </div>
                  <div style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-primary)', marginTop: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {node.name}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    {node.metrics?.chunks ?? 0} blocks
                  </div>
                </div>
              );
            })}
          </div>

          {/* Details Sidebar */}
          {selectedNode && (
            <div style={{ backgroundColor: '#18181b', borderRadius: '6px', border: '1px solid var(--border-color)', padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  {selectedNode.type}
                </span>
                <h3 style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)', marginTop: '2px', wordBreak: 'break-word' }}>
                  {selectedNode.name}
                </h3>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                  {selectedNode.id}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)', fontWeight: '600', marginBottom: '4px' }}>
                  Imports ({outgoingLinks.length}):
                </div>
                {outgoingLinks.length === 0 ? (
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>None</span>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    {outgoingLinks.map((l, i) => (
                      <div key={i} style={{ fontSize: '12px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                        ➔ {l.target.split('/').pop()}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)', fontWeight: '600', marginBottom: '4px' }}>
                  Imported by ({incomingLinks.length}):
                </div>
                {incomingLinks.length === 0 ? (
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>None</span>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    {incomingLinks.map((l, i) => (
                      <div key={i} style={{ fontSize: '12px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                        ⬅ {l.source.split('/').pop()}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
