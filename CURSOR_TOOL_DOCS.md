# Cursor CLI Tool - Learnings & Documentation

## Overview
Cursor CLI is an AI-powered development tool that integrates with Visual Studio Code to provide intelligent coding assistance via agent-driven workflows.

## Installation
- Located at: `/home/clawd/.local/bin/cursor-agent`
- Installed via npm/package manager
- Creates binary in user's local bin directory

## Basic Usage

### Command Structure
```bash
cursor-agent [preset] [options] <task>
```

### Available Presets
- **plan** - Non-interactive planning mode (what we'll use)
- **code** - Interactive coding mode
- **review** - Code review mode
- **test** - Test generation mode

### Common Command Examples
```bash
# Run in planning mode (non-interactive)
cursor-agent --preset plan "Create technical specification for module X"

# Code generation with rules
cursor-agent --preset code --rules "security-focused,Python" "Implement authentication"

# With project context
cursor-agent --preset plan --rules-file project-rules.md "Design API endpoints"
```

## Key Features

### 1. Context-Aware Development
- Understands project structure
- Reads existing code context
- Maintains conversation history
- Uses codebase as reference

### 2. Rule-Based Development
Can enforce project-specific rules via:
- `--rules` flag (inline rules)
- `--rules-file` flag (file-based rules)
- `.cursorrules` file in project root

### 3. Agent Capabilities
- **Planning**: Breaks down complex tasks into steps
- **Coding**: Generates code with context awareness
- **Review**: Analyzes code for issues/improvements
- **Testing**: Creates test cases

### 4. Integration with VS Code
- Seamless VS Code extension
- Real-time code suggestions
- Inline chat interface
- Terminal integration

## Best Practices for Cursor

### Rule Specification
Always specify:
- **Programming language** (Python, TypeScript, etc.)
- **Security requirements** (never commit secrets, validate inputs)
- **Code style** (PEP8, type hints, docstrings)
- **Architecture patterns** (modular, single responsibility)

Example rules string:
```
Python development, PEP8 style, type hints required, use .env for secrets, modular architecture, comprehensive error handling, log everything
```

### Effective Prompting
- Be specific about requirements
- Provide context about project
- Mention constraints upfront
- Specify output format desired

### Security Considerations
- Never include API keys in prompts
- Use placeholder variables
- Reference .env files
- Ask Cursor to verify security practices

## Comparison with Other Tools

### vs GitHub Copilot
- Cursor: Full agent workflows, project context, planning
- Copilot: Inline code suggestions only

### vs ChatGPT/Code Interpreter
- Cursor: Integrated with IDE, codebase awareness
- ChatGPT: General purpose, no IDE integration

### vs Traditional Linters
- Cursor: Proactive suggestions, architectural guidance
- Linters: Reactive, syntax/style focused

## Common Use Cases

1. **Specification Creation** (what we're doing)
   - Generate comprehensive technical specs
   - Create architecture diagrams
   - Design interaction flows

2. **Code Generation**
   - Generate boilerplate code
   - Implement functions/classes
   - Create tests

3. **Refactoring**
   - Restructure existing code
   - Improve performance
   - Update patterns

4. **Documentation**
   - Generate docstrings
   - Create README files
   - Write technical docs

5. **Debugging**
   - Analyze error patterns
   - Suggest fixes
   - Explain complex code

## Limitations

- Requires clear context for best results
- May hallucinate if codebase is unfamiliar
- Still needs human oversight for production code
- Can be slow for very large codebases

## Tips for Success

1. **Start with planning mode** for complex tasks
2. **Be explicit about rules and constraints**
3. **Provide reference examples** when possible
4. **Iterate in small chunks** rather than large requests
5. **Review all generated code** before committing
6. **Test thoroughly** after Cursor makes changes

## Integration with Development Workflow

### Typical Flow:
1. Use `cursor-agent --preset plan` for design/specification
2. Review and refine the plan
3. Use `cursor-agent --preset code` for implementation
4. Manual review and testing
5. Use `cursor-agent --preset review` for code review
6. Final testing and deployment

### Git Workflow:
- Always create feature branches
- Review Cursor changes before committing
- Use descriptive commit messages
- Never commit generated code directly to main

---

**Documented by:** Kelvin Junior  
**Date:** 2026-02-01  
**Tool Version:** Cursor CLI (cursor-agent)