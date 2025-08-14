# (re)write postcss config in case it also got heredoc lines
cat > postcss.config.js <<'JS'
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
JS
