# Mirror_App

## Environment Variables Setup

1. Copy `Backend/.env.example` to `Backend/.env` and fill in your secrets:
   ```sh
   cp Backend/.env.example Backend/.env
   # Then edit Backend/.env and add your real values
   ```

2. **Do NOT commit your `.env` file!**

3. When running locally, the backend will load variables from `Backend/.env` automatically.

4. When running with Docker:
   ```sh
   docker build -t mirror_app_backend ./Backend
   docker run --env-file Backend/.env -p 8000:8000 mirror_app_backend
   ```

5. For GitHub Actions or cloud deployment, add these variables as repository secrets in GitHub under Settings > Secrets and variables > Actions.

--- 