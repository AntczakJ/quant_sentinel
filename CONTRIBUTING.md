# Contributing to QUANT SENTINEL

## Code of Conduct

Be respectful, professional, and focused on improving the project.

## Getting Started

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/your-feature-name`
3. **Make your changes**
4. **Run tests**: `python tests/run_all_tests.py`
5. **Submit a pull request**

## Code Style Guide

### Python
- Follow PEP 8 standard
- Use type hints for all functions
- Maximum line length: 120 characters
- Use docstrings (Google style)

Example:
```python
def calculate_position(
    analysis_data: dict,
    balance: float,
    user_currency: str
) -> dict:
    """
    Calculate trading position based on analysis.
    
    Args:
        analysis_data: SMC analysis results
        balance: Account balance
        user_currency: User's preferred currency
        
    Returns:
        dict with position details (entry, SL, TP, lot size)
        
    Raises:
        ValueError: If balance is negative
    """
    if balance < 0:
        raise ValueError("Balance cannot be negative")
    # Implementation...
    return position_data
```

### TypeScript/React
- Use `const` and `let`, never `var`
- Explicit return types on functions
- No `any` types
- Use interfaces over types for objects

Example:
```typescript
interface TradeSignal {
  symbol: string;
  direction: 'BUY' | 'SELL' | 'HOLD';
  confidence: number;
  timestamp: Date;
}

export async function getSignal(symbol: string): Promise<TradeSignal> {
  // Implementation...
}
```

## Commit Messages

Follow conventional commits format:

```
type(scope): subject

body

footer
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `refactor`: Code restructuring
- `perf`: Performance improvements
- `test`: Test updates
- `chore`: Build, dependencies, etc.

Examples:
```
feat(market): add WebSocket support for live prices
fix(ml): fix LSTM prediction accuracy calculation
docs(api): update API endpoint documentation
perf(scanner): optimize market scanning algorithm
```

## Pull Request Process

1. **Clear description**: Explain what and why
2. **Reference issues**: Link to relevant GitHub issues
3. **Keep it focused**: One feature per PR
4. **Quality checks**:
   - TypeScript: `npm run type-check && npm run lint`
   - Python: `flake8 src/ && pylint src/`
   - Tests: `python tests/run_all_tests.py`

5. **Code review**: Be open to feedback

## Testing Requirements

### For Python changes
```bash
cd /project/root
python -m pytest tests/ -v --cov=src
```

### For TypeScript changes
```bash
cd frontend
npm run type-check
npm run lint
npm test  # if applicable
```

## Documentation

Update documentation when:
- Adding new API endpoints
- Changing configuration options
- Adding major features
- Fixing bugs that affect users

Update files:
- `README.md` for user-facing info
- `DEVELOPMENT.md` for development info
- Code comments for complex logic
- Function docstrings

## Performance Guidelines

### Frontend
- Keep components focused (single responsibility)
- Memoize expensive calculations
- Avoid unnecessary re-renders
- Lazy load routes and components

### Backend
- Cache API responses when appropriate
- Use database indexes
- Optimize database queries
- Implement rate limiting

## Security Best Practices

1. **Never commit secrets**
   - Use `.env` files (not in git)
   - Reference secrets by key, not value

2. **Input validation**
   - Validate all user inputs
   - Use Pydantic for API validation
   - Sanitize database queries

3. **Error messages**
   - Don't expose internal details
   - Log full errors internally
   - Return generic messages to users

## Performance Checklist

Before submitting a PR:

- [ ] TypeScript: `npm run type-check` passes
- [ ] ESLint: `npm run lint` passes without warnings
- [ ] Python: `flake8 src/ && pylint src/` passes
- [ ] Tests: All tests pass locally
- [ ] No hardcoded paths or credentials
- [ ] Meaningful commit messages
- [ ] PR description is clear
- [ ] Code is readable and documented

## Getting Help

- **Documentation**: See `DEVELOPMENT.md`
- **Issues**: Check existing issues or create new one
- **Discussions**: For questions and ideas

## License

By contributing, you agree your code will be licensed under the same license as the project.

---

Thank you for contributing to QUANT SENTINEL! 🚀

