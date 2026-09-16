from fastapi import FastAPI
from app.middleware.user_id_middleware import UserIdMiddleware
from app.configuration.support_incidents import install_support_incident_reporting
from app.error_contract import install_error_handlers
from starlette.middleware.cors import CORSMiddleware

from app.controllers.assignments_controller import AssignmentsController
from app.controllers.branch_types_controller import BranchTypesController
from app.controllers.restaurant_controller import RestaurantController
from app.controllers.verticals_controller import VerticalsController
from app.controllers.tables_controller import TablesController
from app.controllers.branches_controller import BranchesController
from app.controllers.categories_controller import CategoriesController
from app.controllers.clients_controller import ClientsController
from app.controllers.closings_controller import ClosingsController
from app.controllers.confirmations_controller import ConfirmationsController
from app.controllers.consecutives_controller import ConsecutivesController
from app.controllers.dashboard_controller import DashboardController
from app.controllers.departments_controller import DepartmentsController
from app.controllers.orders_controller import OrdersController
from app.controllers.products_controller import ProductsController
from app.controllers.sessions_controller import SessionsController
from app.controllers.sales_controller import SalesController
from app.controllers.stores_controller import StoresController
from app.controllers.terminals_controller import TerminalsController


class FastApiConfig:
    def __init__(self):
        self.app = self._create_app()
        install_support_incident_reporting(self.app, 'store-api')
        install_error_handlers(self.app)
        self._configure_cors()
        self.app.add_middleware(UserIdMiddleware)
        AssignmentsController(self.app)
        BranchTypesController(self.app)
        TablesController(self.app)
        RestaurantController(self.app)
        VerticalsController(self.app)
        BranchesController(self.app)
        CategoriesController(self.app)
        ClientsController(self.app)
        ClosingsController(self.app)
        ConfirmationsController(self.app)
        ConsecutivesController(self.app)
        DashboardController(self.app)
        DepartmentsController(self.app)
        OrdersController(self.app)
        ProductsController(self.app)
        SalesController(self.app)
        SessionsController(self.app)
        StoresController(self.app)
        TerminalsController(self.app)

    def _create_app(self) -> FastAPI:
        app = FastAPI(
            title="Cross-Docking API",
            description="API for managing cross-docking orders",
            version="1.0.0",
            docs_url="/docs",
            redoc_url=None,
            openapi_url="/openapi.json",
            redirect_slashes=False,
        )

        return app

    def _configure_cors(self):
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*", "https://uploads.tsuru.jcampos.dev"],
            # First-party FE surfaces (POS, dashboard, landing, template examples,
            # provisioned org storefronts) must stay allowed even if the wildcard
            # above is ever narrowed.
            allow_origin_regex=r"^https://([a-z0-9-]+\.)*jcampos\.dev$",
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
            max_age=600,
        )

    def get_app(self) -> FastAPI:
        return self.app
