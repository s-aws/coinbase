const { useState, useEffect, useRef } = React;

const App = () => {
    const [theme, setTheme] = useState('light');

    const toggleTheme = () => {
        const newTheme = theme === 'light' ? 'dark' : 'light';
        setTheme(newTheme);
        document.body.className = newTheme;
    };

    return (
        <Dashboard theme={theme} toggleTheme={toggleTheme} />
    );
};

const Dashboard = ({ theme, toggleTheme }) => {
    const [trades, setTrades] = useState([]);
    const [tickerData, setTickerData] = useState([]);
    const [products, setProducts] = useState([]);
    const [selectedProduct, setSelectedProduct] = useState('');
    const [startDate, setStartDate] = useState('');
    const [endDate, setEndDate] = useState('');
    const ws = useRef(null);

    useEffect(() => {
        document.body.className = theme;
    }, [theme]);

    useEffect(() => {
        ws.current = new WebSocket('ws://localhost:8765');

        ws.current.onopen = () => {
            console.log('WebSocket connected');
            ws.current.send(JSON.stringify({ type: 'request_products' }));
        };

        ws.current.onmessage = (event) => {
            const message = JSON.parse(event.data);
            if (message.type === 'state_update') {
                const newTrades = Object.values(message.data.orders);
                setTrades(prevTrades => [...prevTrades, ...newTrades]);
            } else if (message.type === 'ticker') {
                setTickerData(prevData => [...prevData, message.data]);
            } else if (message.type === 'products_list') {
                const allProducts = [...message.derivatives, ...message.spot];
                setProducts(allProducts);
                if (allProducts.length > 0) {
                    setSelectedProduct(allProducts[0]);
                }
            }
        };

        ws.current.onclose = () => {
            console.log('WebSocket disconnected');
        };

        return () => {
            ws.current.close();
        };
    }, []);

    const filteredTrades = trades.filter(trade => {
        const tradeDate = new Date(trade.created_at);
        const start = startDate ? new Date(startDate) : null;
        const end = endDate ? new Date(endDate) : null;
        return trade.product_id === selectedProduct &&
               (!start || tradeDate >= start) &&
               (!end || tradeDate <= end);
    });

    const filteredTickerData = tickerData.filter(data => {
        const tickerDate = new Date(data.time);
        const start = startDate ? new Date(startDate) : null;
        const end = endDate ? new Date(endDate) : null;
        return data.product_id === selectedProduct &&
               (!start || tickerDate >= start) &&
               (!end || tickerDate <= end);
    });

    const exportToCSV = () => {
        const headers = ['Order ID', 'Product ID', 'Side', 'Price', 'Size', 'Timestamp'];
        const rows = filteredTrades.map(trade => [
            trade.order_id,
            trade.product_id,
            trade.side,
            trade.price,
            trade.size,
            trade.created_at
        ].join(','));

        const csvContent = "data:text/csv;charset=utf-8," + [headers.join(','), ...rows].join('\n');
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", `trades_${selectedProduct}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

    return (
        <div>
            <div className="dashboard-header">
                <h1>Trading Dashboard</h1>
                <div className="controls">
                    <select onChange={(e) => setSelectedProduct(e.target.value)} value={selectedProduct}>
                        {products.map(product => <option key={product} value={product}>{product}</option>)}
                    </select>
                    <input type="date" onChange={(e) => setStartDate(e.target.value)} value={startDate} />
                    <input type="date" onChange={(e) => setEndDate(e.target.value)} value={endDate} />
                    <button onClick={exportToCSV}>Export to CSV</button>
                    <button onClick={toggleTheme}>
                        {theme === 'light' ? 'Dark Mode' : 'Light Mode'}
                    </button>
                </div>
            </div>
            <div className="card">
                <TradeChart trades={filteredTrades} tickerData={filteredTickerData} theme={theme} />
            </div>
        </div>
    );
};

const TradeChart = ({ trades, tickerData, theme }) => {
    const svgRef = useRef();
    const tooltipRef = useRef();

    useEffect(() => {
        const svg = d3.select(svgRef.current);
        svg.selectAll('*').remove(); // Clear previous chart

        if (!trades.length && !tickerData.length) return;

        const width = svg.node().getBoundingClientRect().width;
        const height = 400;
        svg.attr('height', height);

        const allData = [
            ...trades.map(d => ({ ...d, type: 'trade', date: new Date(d.created_at), price: parseFloat(d.price) })),
            ...tickerData.map(d => ({ ...d, type: 'ticker', date: new Date(d.time * 1000), price: parseFloat(d.price) }))
        ].filter(d => d.price && isFinite(d.price) && d.date instanceof Date && !isNaN(d.date));

        if (allData.length === 0) {
            return; // No valid data to plot
        }

        const xScale = d3.scaleTime()
            .domain(d3.extent(allData, d => d.date))
            .range([0, width - 60]);

        const yScale = d3.scaleLinear()
            .domain(d3.extent(allData, d => d.price))
            .range([height - 40, 0]);

        const xAxis = d3.axisBottom(xScale);
        const yAxis = d3.axisLeft(yScale);

        const chart = svg.append('g').attr('transform', 'translate(50, 20)');

        chart.append('g').attr('class', 'x-axis').attr('transform', `translate(0, ${height - 40})`).call(xAxis);
        chart.append('g').attr('class', 'y-axis').call(yAxis);

        const tradeLine = d3.line()
            .x(d => xScale(d.date))
            .y(d => yScale(d.price));

        const validTrades = trades
            .map(d => ({...d, date: new Date(d.created_at), price: parseFloat(d.price)}))
            .filter(d => d.price && isFinite(d.price) && d.date instanceof Date && !isNaN(d.date))
            .sort((a, b) => a.date - b.date);

        chart.append('path')
            .datum(validTrades)
            .attr('fill', 'none')
            .attr('stroke', 'steelblue')
            .attr('stroke-width', 1.5)
            .attr('d', tradeLine);

        chart.selectAll('.trade-dot')
            .data(validTrades)
            .enter().append('circle')
            .attr('class', 'trade-dot')
            .attr('cx', d => xScale(d.date))
            .attr('cy', d => yScale(d.price))
            .attr('r', 3)
            .attr('fill', 'steelblue');

        const tickerLine = d3.line()
            .x(d => xScale(d.date))
            .y(d => yScale(d.price));

        const validTickerData = tickerData
            .map(d => ({...d, date: new Date(d.time * 1000), price: parseFloat(d.price)}))
            .filter(d => d.price && isFinite(d.price) && d.date instanceof Date && !isNaN(d.date))
            .sort((a,b) => a.date - b.date);
            
        chart.append('path')
            .datum(validTickerData)
            .attr('fill', 'none')
            .attr('stroke', 'orange')
            .attr('stroke-width', 1.5)
            .attr('d', tickerLine);

    }, [trades, tickerData, theme]);

    return (
        <div>
            <svg ref={svgRef} className="trade-chart"></svg>
            <div ref={tooltipRef} className="tooltip" style={{ opacity: 0 }}></div>
        </div>
    );
};

ReactDOM.render(<App />, document.getElementById('root'));
