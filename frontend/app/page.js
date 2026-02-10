export default function Home() {
  return React.createElement('div', { 
    style: { 
      padding: '50px', 
      fontFamily: 'Arial, sans-serif',
      textAlign: 'center'
    }
  }, [
    React.createElement('h1', { key: 'title' }, '🚀 SOWKNOW4'),
    React.createElement('p', { key: 'subtitle' }, 'Multi-Generational Legacy Knowledge System'),
    React.createElement('div', { 
      key: 'status',
      style: { 
        marginTop: '30px', 
        padding: '20px', 
        background: '#f5f5f5', 
        borderRadius: '10px',
        display: 'inline-block'
      }
    }, [
      React.createElement('h2', { key: 'status-title' }, 'System Status'),
      React.createElement('ul', { key: 'status-list' }, [
        React.createElement('li', { key: 'backend' }, '✅ Backend API: Running'),
        React.createElement('li', { key: 'postgres' }, '✅ PostgreSQL: Running'),
        React.createElement('li', { key: 'redis' }, '✅ Redis: Running'),
        React.createElement('li', { key: 'frontend' }, '✅ Frontend: Running')
      ])
    ])
  ]);
}
