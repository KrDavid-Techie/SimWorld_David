import json
import random
from enum import Enum, auto

from simworld.citygen.road.road_generator import RoadGenerator
from simworld.citygen.building.building_generator import BuildingGenerator
from simworld.citygen.element.element_generator import ElementGenerator
from simworld.citygen.route.route_generator import RouteGenerator
from simworld.citygen.dataclass import *

class GenerationState(Enum):
    """Enum to track the generation state"""
    GENERATING_ROADS = auto()
    GENERATING_BUILDINGS = auto()
    GENERATING_ELEMENTS = auto()
    GENERATING_ROUTES = auto()
    COMPLETED = auto()

class CityGenerator:
    """Manages the complete city generation process including roads, buildings, and elements"""

    def __init__(self, config):
        self.config = config
        random.seed(self.config['simworld.seed'])

        self.building_types, self.building_colors, self.element_types, \
            self.element_colors, self.element_offsets, self.map_element_offsets = self._load_bounding_boxes()

        # Initialize generator
        self.road_generator = RoadGenerator(self.config)
        self.building_generator = BuildingGenerator(self.config, self.building_types)
        self.element_generator = ElementGenerator(self.config, self.element_types, self.map_element_offsets)
        self.route_generator = RouteGenerator(self.config)

        # Initialize generation state
        self.generation_state = GenerationState.GENERATING_ROADS

        # for element generation
        self.current_segment_index = 0
        self.current_building_index = 0
        self.current_element_segment_index = 0

        self.input_path = self.config['citygen.input_roads']
        self.input = self.config['citygen.input_layout']


    def generate(self):
        """Generate the city"""
        while not self.is_generation_complete():
            self.generate_step()

    def generate_step(self) -> bool:
        """Generate one step of the city. Returns True if generation is complete."""
        # generate roads
        if self.generation_state == GenerationState.GENERATING_ROADS:
            # generate roads randomly
            if not self.input:
                if len(self.roads) == 0:
                    print('Generating roads randomly')
                    # Initialize road generation
                    self.road_generator.generate_initial_segments()
                # check if the number of roads has reached the limit
                if len(self.roads) >= self.config['citygen.road.segment_count_limit']:
                    self.road_generator.find_intersections()
                    self.generation_state = GenerationState.GENERATING_BUILDINGS
                    return False
                # continue generating roads
                self.road_generator.generate_step()
                return False
            # generate roads from existing file
            else:
                print(f'Generating roads from existing file {self.input_path}')
                self.generation_state = GenerationState.GENERATING_BUILDINGS
                return self.road_generator.generate_roads_from_file(self.input_path)

        # generate buildings
        elif self.generation_state == GenerationState.GENERATING_BUILDINGS:
            if self.current_segment_index < len(self.roads):
                segment = self.roads[self.current_segment_index]
                self.building_generator.generate_buildings_along_segment(segment, self.road_quadtree)
                self.current_segment_index += 1
                return False
            else:
                # self.building_generator.filter_overlapping_buildings(self.road_quadtree)  not use anymore
                self.generation_state = GenerationState.GENERATING_ELEMENTS
                self.current_segment_index = 0
                return False

        # generate elements
        elif self.generation_state == GenerationState.GENERATING_ELEMENTS:
            if not self.config['citygen.element.generation']:
                self.generation_state = GenerationState.GENERATING_ROUTES
                return False

            if self.current_building_index < len(self.buildings):
                # Generate elements around buildings
                if self.config['citygen.element.generation_thread_number']:
                    thread_num = self.config['citygen.element.generation_thread_number']
                    # generate elements around multiple buildings in one time
                    buildings = self.buildings[self.current_building_index:min(self.current_building_index + thread_num, len(self.buildings))]
                    self.element_generator.generate_elements_around_buildings_multithread(buildings)
                    self.current_building_index += min(thread_num, len(self.buildings) - self.current_building_index)
                else:
                    building = self.buildings[self.current_building_index]
                    self.element_generator.generate_elements_around_building(building)
                    self.current_building_index += 1
                self.element_generator.filter_elements_by_buildings(self.building_quadtree)
                return False
            # Generate elements on roads
            if self.current_element_segment_index < len(self.roads):
                if self.config['citygen.element.generation_thread_number']:
                    thread_num = self.config['citygen.element.generation_thread_number']
                    segments = self.roads[self.current_element_segment_index:min(self.current_element_segment_index + thread_num, len(self.roads))]
                    self.element_generator.generate_elements_on_road_multithread(segments)
                    self.current_element_segment_index += min(thread_num, len(self.roads) - self.current_element_segment_index)
                else:
                    pass
                return False
            else:
                self.generation_state = GenerationState.GENERATING_ROUTES
                return False

        # generate routes
        elif self.generation_state == GenerationState.GENERATING_ROUTES:
            if not self.config['citygen.route.generation']:
                self.generation_state = GenerationState.COMPLETED
                return True
            # Generate routes
            print('Generating routes')
            target_data_list = []
            for _ in range(self.config['citygen.route.number']):
                target_point = self.route_generator.generate_target_point_randomly()
                target_label = self.route_generator.get_point_around_label(target_point, self.city_quadtrees)
                target_data = {
                    'label': target_label,
                    'point': target_point.to_dict()
                }
                target_data_list.append(target_data)
            self.generation_state = GenerationState.COMPLETED
        return True

    def is_generation_complete(self) -> bool:
        """Check if city generation is complete"""
        return self.generation_state == GenerationState.COMPLETED

    def _load_bounding_boxes(self):
        with open(self.config['citygen.input_bounding_boxes'], 'r') as f:
            data = json.load(f)
        buildings = data['buildings']
        elements = data['elements']

        # Define different types of buildings
        BUILDING_TYPES = []
        BUILDING_COLORS = {}

        # Define different types of elements
        ELEMENT_TYPES = []
        ELEMENT_COLORS = {}

        for name, building in buildings.items():
            x = building['bbox']['x'] / 100     # scaling for easy generation
            y = building['bbox']['y'] / 100

            BUILDING_TYPES.append(BuildingType(name, x, y, is_required='Building' not in name))
            BUILDING_COLORS[name] = "#{:06x}".format(random.randint(0, 0xFFFFFF))

        for name, element in elements.items():
            x = element['bbox']['x'] / 100
            y = element['bbox']['y'] / 100
            ELEMENT_TYPES.append(ElementType(name, x, y))
            ELEMENT_COLORS[name] = "#{:06x}".format(random.randint(0, 0xFFFFFF))

        ELEMENT_OFFSETS = {}
        for element_type in ELEMENT_TYPES:
            # TODO: add parking offset
            if element_type.name.lower().startswith("bp_tree"):
                ELEMENT_OFFSETS[element_type.name] = self.config['citygen.element.tree_offset']
            else:
                ELEMENT_OFFSETS[element_type.name] = self.config['citygen.element.furniture_offset']

        MAP_ELEMENT_OFFSETS = {}
        for name, offset in ELEMENT_OFFSETS.items():
            MAP_ELEMENT_OFFSETS[offset] = MAP_ELEMENT_OFFSETS.get(offset, []) + [name]

        return BUILDING_TYPES, BUILDING_COLORS, ELEMENT_TYPES, ELEMENT_COLORS, ELEMENT_OFFSETS, MAP_ELEMENT_OFFSETS

    @property
    def city_quadtrees(self):
        return [self.road_quadtree, self.building_quadtree, self.element_quadtree]

    @property
    def roads(self):
        return self.road_generator.road_manager.roads

    @property
    def routes(self):
        return self.route_generator.route_manager.routes

    @property
    def road_quadtree(self):
        return self.road_generator.road_manager.road_quadtree

    @property
    def building_quadtree(self):
        return self.building_generator.building_manager.building_quadtree

    @property
    def element_quadtree(self):
        return self.element_generator.element_manager.element_quadtree

    @property
    def intersections(self):
        return self.road_generator.road_manager.intersections

    @property
    def buildings(self):
        return self.building_generator.building_manager.buildings

    @property
    def elements(self):
        return self.element_generator.element_manager.elements

    @property
    def road_manager(self):
        return self.road_generator.road_manager

    @property
    def building_manager(self):
        return self.building_generator.building_manager
    
    @property
    def element_manager(self):
        return self.element_generator.element_manager
    
    @property
    def route_manager(self):
        return self.route_generator.route_manager
        
